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
    Lógica de extração baseada em Ancora (Context-Aware) v2
    Melhoria 10x na precisão: Upscaling + Next-Line Priority + Header Cleaning
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
    if any(x in clean_text for x in ['HABILITACAO', 'CONDUTOR', 'CNH', 'DRIVER', 'PERMISO', 'PERMISSION']):
        result['tipo_documento'] = 'CNH'
    elif 'NACIONAL' in clean_text and 'TERRITORIO' in clean_text:
        result['tipo_documento'] = 'CNH' # Carteira Nacional validade em todo Territorio
    elif any(x in clean_text for x in ['IDENTIDADE', 'SSP', 'SECRETARIA', 'REGISTRO GERAL']):
        result['tipo_documento'] = 'RG'

    # --- 2. CPF (Busca por Ancora) ---
    cpf_pattern = r'(\d{3}[\.\s]?\d{3}[\.\s]?\d{3}[-\s]?\d{2})'
    
    for i, line in enumerate(lines):
        upper = line.upper()
        if 'CPF' in upper:
            # Estrategia 1: CPF na mesma linha (strip label)
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
                    
    # Fallback CPF global
    if not result['cpf']:
        matches = re.findall(cpf_pattern, clean_text)
        for m in matches:
             if '.' in m or '-' in m: # Exige pontuacao no fallback para evitar lixo
                 result['cpf'] = format_cpf(m)
                 break

    # --- 3. Data Nascimento ---
    date_pattern = r'\d{2}/\d{2}/\d{4}'
    for i, line in enumerate(lines):
        upper = line.upper()
        if 'NASCIMENTO' in upper or 'NASC' in upper:
             d = re.search(date_pattern, parse_date_typos(upper)) 
             if d:
                 result['data_nascimento'] = d.group(0)
                 break
             if i + 1 < len(lines):
                 d2 = re.search(date_pattern, parse_date_typos(lines[i+1].upper()))
                 if d2:
                     result['data_nascimento'] = d2.group(0)
                     break
    
    # --- 4. RG ---
    rg_keywords = ['RG', 'REGISTRO', 'IDENTIDADE', 'DOC. IDENT']
    for i, line in enumerate(lines):
        upper = line.upper()
        # Se contem keyword do RG e NAO contem CPF (para nao confundir labels)
        if any(k in upper for k in rg_keywords) and 'CPF' not in upper:
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
             
    if not result['rg']:
         # Fallback agressivo: numeros soltos grandes que nao sejam data nem cpf
         candidates = re.findall(r'\b\d{7,12}\b', clean_text)
         for c in candidates:
             if not is_same_number(c, result['cpf']) and not is_date(c):
                 result['rg'] = c
                 break

    # --- 5. Nome (Lógica Melhorada) ---
    headers_to_strip = ['NOME SOCIAL', 'NOME E SOBRENOME', 'NOME', 'SOBRENOME', 'RNTRC', 'ASSINATURA']
    name_found = False
    
    for i, line in enumerate(lines):
        upper = line.upper()
        
        if 'NOME' in upper:
             # >>>> Tenta PRIMEIRO a proxima linha (Padrao CNH) <<<<
             if i + 1 < len(lines):
                 cand = lines[i+1].upper()
                 cand_clean = re.sub(r'[^A-Z\s]', '', cand).strip()
                 # Verifica se é um nome válido
                 if is_valid_name_simple(cand_clean):
                     result['nome_provavel'] = cand_clean
                     name_found = True
                     break

             # Se nao deu, tenta a mesma linha (limpando o header)
             cleaned_line = upper
             for h in headers_to_strip:
                 cleaned_line = cleaned_line.replace(h, '')
             
             cleaned_line = cleaned_line.strip()
             cleaned_line = re.sub(r'[^A-Z\s]', '', cleaned_line) # Tira lixo
             
             if is_valid_name_simple(cleaned_line):
                 result['nome_provavel'] = cleaned_line
                 name_found = True
                 break
    
    # Fallback Nome: Procura linha com apenas letras maiusculas
    if not result['nome_provavel']:
         blacklist_global = ['REPUBLICA', 'FEDERATIVA', 'MINISTERIO', 'CARTEIRA', 'NACIONAL', 'HABILITACAO', 'VALIDA', 'TERRITORIO']
         for line in lines:
             l = line.upper().strip()
             if len(l) < 5 or any(c.isdigit() for c in l): continue
             if is_valid_name_simple(l):
                 # Reforço: verifica blacklist global
                 if not any(b in l for b in blacklist_global):
                     result['nome_provavel'] = l
                     break

    return result

def format_cpf(raw):
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
    return text.replace('O', '0').replace('o', '0')

def is_valid_name_simple(text):
    text = text.strip()
    # Aumentar rigor: min 5 chars
    if len(text) < 5: return False
    words = text.split()
    # Min 2 palavras
    if len(words) < 2: return False
    
    # Rejeitar palavras header ou lixo
    blacklist = ['REPUBLICA', 'FEDERATIVA', 'MINISTERIO', 'CARTEIRA', 'NACIONAL', 'HABILITACAO', 'VALIDA', 'TERRITORIO', 'FILIACAO', 'SOBRI', 'ACAO']
    for b in blacklist:
        if b in text: return False
        
    # Rejeitar se palavras forem todas muito curtas (ex: "E E A O")
    long_words = [w for w in words if len(w) > 2]
    if len(long_words) == 0: return False
        
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

    # --- MELHORIA 1: UPSCALE (2x) ---
    # Aumentar a resolução ajuda MUITO o Tesseract em letras pequenas
    # Se a imagem for pequena (< 2000px de largura), dobra.
    h, w = img.shape[:2]
    if w < 2000:
        scale = 2.0
        # Upscaling ajuda a definir bordas
        img = cv2.resize(img, None, fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC)

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
