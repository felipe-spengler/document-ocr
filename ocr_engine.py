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
    Lógica de extração baseada em Regex e Heuristica (Portada do JS e melhorada)
    """
    lines = [line.strip() for line in text.split('\n') if len(line.strip()) > 2]
    
    result = {
        "cpf": None,
        "data_nascimento": None,
        "rg": None,
        "nome_provavel": None,
        "tipo_documento": "DESCONHECIDO"
    }

    clean_text = text.replace('\r', '').upper()
    
    # --- 1. Tipo ---
    if any(x in clean_text for x in ['HABILITACAO', 'CONDUTOR', 'CNH', 'DRIVER', 'PERMISO']):
        result['tipo_documento'] = 'CNH'
    elif any(x in clean_text for x in ['IDENTIDADE', 'SSP', 'SECRETARIA']):
        result['tipo_documento'] = 'RG'

    # --- 2. CPF ---
    # Regex flexivel
    cpf_match = re.search(r'(\d{3})[\.\s]?(\d{3})[\.\s]?(\d{3})[-\s]?(\d{2})', clean_text)
    if cpf_match:
        result['cpf'] = f"{cpf_match.group(1)}.{cpf_match.group(2)}.{cpf_match.group(3)}-{cpf_match.group(4)}"
    
    # --- 3. Datas ---
    # Encontrar todas as datas
    date_pattern = r'\d{2}/\d{2}/\d{4}'
    all_dates = re.findall(date_pattern, clean_text)
    
    # Tentar achar a data de nascimento pela label
    nasc_date = None
    for i, line in enumerate(lines):
        upper_line = line.upper()
        if 'NASCIMENTO' in upper_line or 'NASC' in upper_line:
            # Tenta achar na mesma linha
            d = re.search(date_pattern, line)
            if d:
                nasc_date = d.group(0)
                break
            # Tenta na proxima
            if i + 1 < len(lines):
                d2 = re.search(date_pattern, lines[i+1])
                if d2:
                    nasc_date = d2.group(0)
                    break
    
    if nasc_date:
        result['data_nascimento'] = nasc_date
    elif all_dates:
        # Fallback: pegar a data mais antiga (assumindo que nasc < expedicao < validade)
        try:
            sorted_dates = sorted(all_dates, key=lambda d: datetime.strptime(d, "%d/%m/%Y"))
            # Filtra datas invalidas (ex: ano < 1900)
            valid_dates = [d for d in sorted_dates if datetime.strptime(d, "%d/%m/%Y").year > 1900]
            if valid_dates:
                result['data_nascimento'] = valid_dates[0]
        except:
            pass

    # --- 4. RG ---
    # Evitar pegar a propria data como RG (ex: 23052023) ou o CPF
    clean_cpf = result['cpf'].replace('.', '').replace('-', '') if result['cpf'] else '99999999999'
    
    # Regex RG chatinha, vamos tentar pegar sequencias numericas grandes que nao sejam CPF nem Data
    # RG geralmente tem pontos, mas OCR falha.
    # Estrategia: Pegar numeros de 7 a 12 digitos
    potential_rgs = re.findall(r'(\d[\d\.\-]{5,15})', clean_text)
    
    for pot in potential_rgs:
        nums = re.sub(r'\D', '', pot)
        
        # Filtros
        if nums == clean_cpf: continue
        if len(nums) < 5: continue
        
        # É uma data? (ddmmyyyy ou ddmmyy)
        if len(nums) == 8:
            # check se parece data (dia <=31, mes <=12)
            try:
                d = int(nums[0:2])
                m = int(nums[2:4])
                y = int(nums[4:8])
                if d <= 31 and m <= 12 and (1900 < y < 2100):
                    continue # É provalmente uma data
            except:
                pass
        
        # Se passou, é um forte candidato a RG
        result['rg'] = pot
        break

    # --- 5. Nome ---
    # Blacklist de palavras comuns em headers
    blacklist = ['REQUBLICA', 'REPUBLICA', 'FEDERATIVA', 'BRASIL', 'MINISTERIO', 'IDENTIDADE', 
                 'CARTEIRA', 'NACIONAL', 'HABILITACAO', 'DETRAN', 'ASSINATURA', 'VALIDA', 
                 'DATA', 'NOME', 'FILIACAO', 'DOCUMENTO', 'ESTADO', 'SECRETARIA', 'CPF', 
                 'GERAL', 'REGISTRO', 'LEI', 'LOCAL', 'SOBRENOME', 'SOCIAL', 'PAI', 'MAE', 'DOC']

    # Procurar Ancora "NOME"
    name_candidate = None
    for i, line in enumerate(lines):
        upper_line = line.upper()
        # Limpeza basica de caracteres estranhos da linha
        clean_line_alpha = re.sub(r'[^A-Z\s]', '', upper_line).strip()
        
        if 'NOME' in clean_line_alpha and len(clean_line_alpha) < 40: # < 40 pra nao pegar frases
             # Nome pode estar na proxima
             if i + 1 < len(lines):
                 cand = lines[i+1]
                 if is_valid_name(cand, blacklist):
                     name_candidate = cand
                     break
    
    # Fallback: Linha puramente letras maiusculas
    if not name_candidate:
        for line in lines:
            line = line.strip()
            if len(line) < 5 or any(char.isdigit() for char in line): continue
            
            # Verifica caracteres permitidos (A-Z, espaco)
            if not re.match(r'^[A-Z\s\.]+$', line.upper()): continue
            
            if is_valid_name(line, blacklist):
                name_candidate = line
                break
                
    if name_candidate:
        result['nome_provavel'] = name_candidate

    return result

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

def process_image_cv2(image_bytes):
    """
    Pipeline de processamento de imagem com OpenCV (Nível FIFA)
    """
    # Converter bytes para numpy array
    nparr = np.frombuffer(image_bytes, np.uint8)
    img = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
    
    if img is None:
        raise ValueError("Falha ao decodificar imagem")

    # 1. Converter para Grayscale
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    
    # 2. Remover Ruído (Blur suave)
    # Ajuda a remover pontilhados da impressão do RG/CNH
    gray = cv2.medianBlur(gray, 3)

    # 3. Thresholding Adaptativo (O Pulo do Gato)
    # Em vez de um corte fixo (preto/branco), ele analisa a vizinhança do pixel.
    # Isso resolve o problema de sombras e fundos coloridos (verde da CNH)
    thresh = cv2.adaptiveThreshold(gray, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, 
                                   cv2.THRESH_BINARY, 11, 2)
    
    # 4. Operações Morfológicas (Opcional, mas ajuda em fontes finas)
    # kernel = np.ones((1,1), np.uint8)
    # thresh = cv2.dilate(thresh, kernel, iterations=1)
    
    # Opcional: Salvar imagem processada para debug se quiser
    # cv2.imwrite("debug_processed.png", thresh)
    
    return thresh
