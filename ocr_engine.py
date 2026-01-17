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
    # CNH tem muitos termos especificos
    if any(x in clean_text for x in ['HABILITACAO', 'CONDUTOR', 'CNH', 'DRIVER', 'PERMISO', 'PERMISSION']):
        result['tipo_documento'] = 'CNH'
    elif 'NACIONAL' in clean_text and ('TERRITORIO' in clean_text or 'TRANSITO' in clean_text):
        result['tipo_documento'] = 'CNH'
    elif 'MINISTERIO' in clean_text and ('INFRAESTRUTURA' in clean_text or 'CIDADES' in clean_text):
        result['tipo_documento'] = 'CNH'
    elif any(x in clean_text for x in ['IDENTIDADE', 'SSP', 'SECRETARIA', 'REGISTRO GERAL']):
        result['tipo_documento'] = 'RG'

    # --- 2. CPF (Busca por Ancora) ---
    cpf_pattern = r'(\d{3}[\.\s]?\d{3}[\.\s]?\d{3}[-\s]?\d{2})'
    
    for i, line in enumerate(lines):
        upper = line.upper()
        if 'CPF' in upper:
            line_content = upper.replace('CPF', '').strip()
            # Tenta pegar apenas digitos caso a formatacao esteja ruim
            nums_only = re.sub(r'\D', '', line_content)
            if len(nums_only) == 11:
                result['cpf'] = format_cpf(nums_only)
                break
                
            match = re.search(cpf_pattern, line_content)
            if match:
                result['cpf'] = format_cpf(match.group(1))
                break
            
            if i + 1 < len(lines):
                next_line = lines[i+1].upper()
                match = re.search(cpf_pattern, next_line)
                if match:
                    result['cpf'] = format_cpf(match.group(1))
                    break
                    
    if not result['cpf']:
        matches = re.findall(cpf_pattern, clean_text)
        for m in matches:
             if '.' in m or '-' in m: 
                 result['cpf'] = format_cpf(m)
                 break

    # --- 3. Data Nascimento ---
    # Suporte a dd/mm/aaaa e ddmmaaaa (ocr erro)
    date_pattern = r'\d{2}/\d{2}/\d{4}'
    date_pattern_loose = r'\d{8}'
    
    for i, line in enumerate(lines):
        upper = line.upper()
        if 'NASCIMENTO' in upper or 'NASC' in upper:
             # Tenta padrao com barras
             d = re.search(date_pattern, parse_date_typos(upper)) 
             if d:
                 result['data_nascimento'] = d.group(0)
                 break
             
             # Tenta padrao sem barras (ex: 19091981)
             d_loose = re.search(date_pattern_loose, upper)
             if d_loose:
                 raw = d_loose.group(0)
                 # Formata
                 result['data_nascimento'] = f"{raw[:2]}/{raw[2:4]}/{raw[4:]}"
                 break
                 
             if i + 1 < len(lines):
                 next_l = parse_date_typos(lines[i+1].upper())
                 d2 = re.search(date_pattern, next_l)
                 if d2:
                     result['data_nascimento'] = d2.group(0)
                     break
                 d2_loose = re.search(date_pattern_loose, next_l)
                 if d2_loose:
                     raw = d2_loose.group(0)
                     result['data_nascimento'] = f"{raw[:2]}/{raw[2:4]}/{raw[4:]}"
                     break
    
    # --- 4. RG ---
    rg_keywords = ['RG', 'REGISTRO', 'IDENTIDADE', 'DOC. IDENT']
    
    # Prioridade CNH: Campo DOC IDENTIDADE ORG EMISSOR
    doc_ident_idx = -1
    for idx, l in enumerate(lines):
        if 'DOC' in l.upper() and 'IDENTIDADE' in l.upper():
            doc_ident_idx = idx
            break
            
    if doc_ident_idx != -1:
        # Tenta achar o numero nas proximas 2 linhas
        for offset in [0, 1, 2]:
            if doc_ident_idx + offset >= len(lines): break
            line_rg = lines[doc_ident_idx + offset].upper()
            # Procura sequencia de numeros > 5 digitos
            candidates = re.findall(r'\b\d{5,12}\b', line_rg)
            for cand in candidates:
                if not is_same_number(cand, result['cpf']) and not is_date_loose(cand):
                    result['rg'] = cand
                    break
            if result['rg']: break

    # Se nao achou pela label especifica, vai no generico
    if not result['rg']:
        for i, line in enumerate(lines):
            upper = line.upper()
            if any(k in upper for k in rg_keywords) and 'CPF' not in upper:
                 nums = re.findall(r'\b\d{5,12}\b', upper)
                 for num in nums:
                     if not is_same_number(num, result['cpf']) and not is_date_loose(num):
                         result['rg'] = num
                         break
                 if result['rg']: break
                 
                 if i + 1 < len(lines):
                     nums_next = re.findall(r'\b\d{5,12}\b', lines[i+1])
                     for num in nums_next:
                         if not is_same_number(num, result['cpf']) and not is_date_loose(num):
                             result['rg'] = num
                             break
                 if result['rg']: break
                 
    if not result['rg']:
         # Fallback agressivo
         candidates = re.findall(r'\b\d{7,12}\b', clean_text)
         for c in candidates:
             if not is_same_number(c, result['cpf']) and not is_date_loose(c):
                 result['rg'] = c
                 break

    # --- 5. Nome (Mantem logica boa) ---
    headers_to_strip = ['NOME SOCIAL', 'NOME E SOBRENOME', 'NOME', 'SOBRENOME', 'RNTRC', 'ASSINATURA']
    name_found = False
    
    for i, line in enumerate(lines):
        upper = line.upper()
        
        if 'NOME' in upper:
             if i + 1 < len(lines):
                 cand = lines[i+1].upper()
                 cand_clean = re.sub(r'[^A-Z\s]', '', cand).strip()
                 if is_valid_name_simple(cand_clean):
                     result['nome_provavel'] = cand_clean
                     name_found = True
                     break

             cleaned_line = upper
             for h in headers_to_strip:
                 cleaned_line = cleaned_line.replace(h, '')
             
             cleaned_line = cleaned_line.strip()
             cleaned_line = re.sub(r'[^A-Z\s]', '', cleaned_line)
             
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

def is_date_loose(s):
    if len(s) == 8 and (s.startswith('19') or s.startswith('20') or s.endswith('19') or s.endswith('20')): return True
    return False

import google.generativeai as genai
import os
import json

def extract_with_gemini(image_bytes, api_key):
    """
    Usa o Gemini 1.5 Flash (Visão) para extrair dados com precisão humana.
    Requer chave de API configurada.
    """
    try:
        genai.configure(api_key=api_key)
        model = genai.GenerativeModel('gemini-1.5-flash')
        
        # Carregar imagem para o formato que o Gemini aceita
        image_parts = [
            {
                "mime_type": "image/png", # ou jpeg, o Gemini se vira
                "data": image_bytes
            }
        ]
        
        prompt = """
        Analise este documento brasileiro (CNH ou RG) e extraia os dados em JSON estrito.
        Campos requeridos:
        - "nome_provavel": Nome completo.
        - "cpf": Formato XXX.XXX.XXX-XX (Se não houver, null).
        - "data_nascimento": DD/MM/AAAA.
        - "rg": Apenas números (Se não houver, null). Se for CNH, procure o campo 'DOC IDENTIDADE' ou 'REGISTRO'.
        - "tipo_documento": "CNH" ou "RG".
        
        Retorne APENAS o JSON, sem markdown (```json).
        """
        
        response = model.generate_content([prompt, image_parts[0]])
        text = response.text.strip()
        
        # Limpar markdown se houver
        if text.startswith('```json'): # remove ```json
             text = text[7:] 
        if text.endswith('```'): # remove ```
             text = text[:-3]
             
        data = json.loads(text.strip())
        return data
        
    except Exception as e:
        print(f"Erro Gemini: {e}")
        return None

def process_image_pipeline(image_bytes):
    """
    Pipeline que retorna MÚLTIPLAS versões da imagem para tentar OCR.
    Se uma falhar (texto vazio), tentamos a outra.
    """
    nparr = np.frombuffer(image_bytes, np.uint8)
    img = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
    
    if img is None:
        raise ValueError("Falha ao decodificar imagem")

    # --- MELHORIA 1: UPSCALE (Apenas se muito pequena) ---
    h, w = img.shape[:2]
    # Se ja for HD (1000+), nao mexe, senao distorce letras no OCR.
    if w < 1000:
        scale = 2.0
        img = cv2.resize(img, None, fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC)

    # 1. Grayscale (Básico)
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    
    # 2. Otsu
    _, otsu = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    
    # 3. Adaptive
    adaptive = cv2.adaptiveThreshold(gray, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, 
                                     cv2.THRESH_BINARY, 11, 2)
    
    return {
        "original": img, # Fallback final
        "gray": gray,    # Seguro
        "otsu": otsu,    # Alto contraste
        "adaptive": adaptive # Hardcore
    }
