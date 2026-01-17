import cv2
import numpy as np
import pytesseract
from PIL import Image
import base64
import io
import re
from datetime import datetime

# Configurar caminho do tesseract se necessario (no Docker linux padrao geralmente funciona direto)
# pytesseract.pytesseract.tesseract_cmd = r'/usr/bin/tesseract'

def parse_document_text(text):
    """
    Lógica de extração baseada em Ancora (Context-Aware)
    Melhoria 10x na precisão ao buscar dados PERTO dos labels.
    """
    lines = [line.strip() for line in text.split('\n') if len(line.strip()) > 2]
    clean_text = text.replace('\r', '').upper()
    
    result = {
        "cpf": None,
        "data_nascimento": None,
        "rg": None,
        "nome_provavel": None,
        "tipo_documento": "DESCONHECIDO"
    }

    # --- 1. Tipo ---
    if any(x in clean_text for x in ['HABILITACAO', 'CONDUTOR', 'CNH', 'DRIVER', 'PERMISO']):
        result['tipo_documento'] = 'CNH'
    elif any(x in clean_text for x in ['IDENTIDADE', 'SSP', 'SECRETARIA', 'REGISTRO GERAL']):
        result['tipo_documento'] = 'RG'

    # --- 2. CPF (Busca por Ancora) ---
    # Tenta achar a palavra CPF e pegar o numero logo a frente ou abaixo
    cpf_pattern = r'(\d{3}[\.\s]?\d{3}[\.\s]?\d{3}[-\s]?\d{2})'
    
    # Busca Contextual (Linha a linha)
    for i, line in enumerate(lines):
        upper = line.upper()
        if 'CPF' in upper:
            # Estrategia 1: CPF na mesma linha (ex: CPF 123.456...)
            # Remove a palavra CPF para nao atrapalhar
            line_content = upper.replace('CPF', '').strip()
            match = re.search(cpf_pattern, line_content)
            if match:
                result['cpf'] = format_cpf(match.group(1))
                break
            
            # Estrategia 2: CPF na proxima linha
            if i + 1 < len(lines):
                next_line = lines[i+1].upper()
                match = re.search(cpf_pattern, next_line)
                if match:
                    result['cpf'] = format_cpf(match.group(1))
                    break
    
    # Fallback CPF: Se nao achou por ancora, tenta busca global (cuidado com registro)
    if not result['cpf']:
        matches = re.findall(cpf_pattern, clean_text)
        for m in matches:
             # Valida se parece CPF mesmo (pontuação ajuda)
             if '.' in m or '-' in m:
                 result['cpf'] = format_cpf(m)
                 break
    
    # --- 3. Data Nascimento (Busca por Ancora) ---
    date_pattern = r'\d{2}/\d{2}/\d{4}'
    for i, line in enumerate(lines):
        upper = line.upper()
        if 'NASCIMENTO' in upper or 'NASC' in upper:
             # Mesma linha
             d = re.search(date_pattern, parse_date_typos(upper)) # Fix ocr nums
             if d:
                 result['data_nascimento'] = d.group(0)
                 break
             # Proxima linha
             if i + 1 < len(lines):
                 d2 = re.search(date_pattern, parse_date_typos(lines[i+1].upper()))
                 if d2:
                     result['data_nascimento'] = d2.group(0)
                     break
    
    # --- 4. RG / Registro (Busca por Ancora) ---
    # CNH tem "REGISTRO". RG tem "REGISTRO GERAL" ou "RG".
    # Vamos procurar numeros perto dessas palavras
    rg_keywords = ['RG', 'REGISTRO', 'IDENTIDADE', 'DOC. IDENT']
    
    for i, line in enumerate(lines):
        upper = line.upper()
        # Se contem keyword e NAO contem CPF na mesma linha
        if any(k in upper for k in rg_keywords) and 'CPF' not in upper:
             # Tenta achar numero grande na linha
             nums = re.findall(r'\b\d{5,12}\b', upper)
             for num in nums:
                 if not is_same_number(num, result['cpf']):
                     result['rg'] = num
                     break
             if result['rg']: break
             
             # Proxima linha
             if i + 1 < len(lines):
                 nums_next = re.findall(r'\b\d{5,12}\b', lines[i+1])
                 for num in nums_next:
                     if not is_same_number(num, result['cpf']):
                         result['rg'] = num
                         break
             if result['rg']: break
             
    # Fallback RG: Regex solta, mas evitando o CPF ja encontrado
    if not result['rg']:
         candidates = re.findall(r'\b\d{7,12}\b', clean_text)
         for c in candidates:
             if not is_same_number(c, result['cpf']) and not is_date(c):
                 result['rg'] = c
                 break

    # --- 5. Nome (Busca por Ancora Melhorada) ---
    # Limpa cabeçalhos que podem estar colados no nome
    headers_to_strip = ['NOME SOCIAL', 'NOME E SOBRENOME', 'NOME', 'SOBRENOME', 'RNTRC', 'ASSINATURA']
    
    # Tenta achar a ancora "NOME"
    name_found = False
    
    for i, line in enumerate(lines):
        upper = line.upper()
        
        # Se a linha SO contem a label "NOME...", o nome esta embaixo
        if 'NOME' in upper:
             # Verifica se o nome esta NA MESMA linha (ex: NOME FULANO DE TAL)
             cleaned_line = upper
             for h in headers_to_strip:
                 cleaned_line = cleaned_line.replace(h, '')
             
             cleaned_line = cleaned_line.strip()
             cleaned_line = re.sub(r'[^A-Z\s]', '', cleaned_line) # Tira lixo
             
             # Se sobrou algo relevante (>3 chars, 2 palavras), é o nome!
             if is_valid_name_simple(cleaned_line):
                 result['nome_provavel'] = cleaned_line
                 name_found = True
                 break
             
             # Senao, pega a proxima linha
             if i + 1 < len(lines):
                 cand = lines[i+1].upper()
                 # Limpa cand de possiveis sujeiras (pontos, traços)
                 cand_clean = re.sub(r'[^A-Z\s]', '', cand).strip()
                 if is_valid_name_simple(cand_clean):
                     result['nome_provavel'] = cand_clean
                     name_found = True
                     break
    
    return result

def format_cpf(raw):
    # Formata CPF bonitinho
    nums = re.sub(r'\D', '', raw)
    if len(nums) != 11: return raw
    return f"{nums[:3]}.{nums[3:6]}.{nums[6:9]}-{nums[9:]}"

def is_same_number(n1, n2):
    if not n1 or not n2: return False
    return re.sub(r'\D', '', n1) == re.sub(r'\D', '', n2)

def is_date(s):
    # Simplificado
    if len(s) == 8 and (s.startswith('19') or s.startswith('20') or s.endswith('19') or s.endswith('20')): return True
    return False

def parse_date_typos(text):
    # Corrige OCR O->0 em datas
    return text.replace('O', '0').replace('o', '0')

def is_valid_name_simple(text):
    text = text.strip()
    if len(text) < 4: return False
    words = text.split()
    if len(words) < 2: return False
    
    blacklist = ['REPUBLICA', 'FEDERATIVA', 'MINISTERIO', 'CARTEIRA', 'NACIONAL', 'HABILITACAO', 'VALIDA', 'TERRITORIO', 'FILIACAO']
    for b in blacklist:
        if b in text: return False
        
    return True

def is_valid_name(text, blacklist):
    text = text.upper().strip()
    if len(text) < 3: return False
    # Nao pode ter numeros
    if re.search(r'\d', text): return False
    
    # Verificar blacklist
    for bad in blacklist:
         if bad in text: return False
    
    # Deve ter pelo menos 2 palavras (Nome Sobrenome)
    if len(text.split()) < 2: return False
    
    return True

def process_image_pipeline(image_bytes):
    """
    Pipeline que retorna MÚLTIPLAS versões da imagem para tentar OCR.
    Se uma falhar (texto vazio), tentamos a outra.
    """
    nparr = np.frombuffer(image_bytes, np.uint8)
    img = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
    
    if img is None:
        raise ValueError("Falha ao decodificar imagem")

    # 1. Grayscale (Básico)
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    
    # 2. Binarização Otsu (Bom contraste global)
    # Remove fundo cinza/verde uniforme
    _, otsu = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    
    # 3. Adaptive Threshold (Bom para sombras)
    # Cuidado: pode gerar ruido se a imagem for muito nitida
    adaptive = cv2.adaptiveThreshold(gray, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, 
                                     cv2.THRESH_BINARY, 11, 2)
    
    # 4. Denoised
    denoised = cv2.fastNlMeansDenoising(gray, None, 10, 7, 21)

    return {
        "original": img, # Fallback final
        "gray": gray,    # Seguro
        "otsu": otsu,    # Alto contraste
        "adaptive": adaptive # Hardcore
    }
