from fastapi import FastAPI, UploadFile, File, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import BaseModel
import base64
import io
import pytesseract
from PIL import Image
import os
from ocr_engine import process_image_pipeline, parse_document_text, extract_with_gemini

app = FastAPI()

# Configuração CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Esquema de Entrada
class ExtractRequest(BaseModel):
    image: str # Base64 string

# Servir arquivos estáticos (Frontend)
app.mount("/static", StaticFiles(directory="public"), name="static")

@app.get("/status")
def health_check():
    return {"status": "Online", "backend": "Python/OpenCV/Gemini"}

@app.post("/extract")
async def extract_data(request: ExtractRequest):
    try:
        # Limpar header base64
        if "," in request.image:
            header, encoded = request.image.split(",", 1)
        else:
            encoded = request.image
            
        image_bytes = base64.b64decode(encoded)
        
        # --- MODO TURBO: GEMINI AI (Se tiver chave configurada) ---
        gemini_key = os.getenv("GEMINI_API_KEY")
        print(f"[DEBUG] GEMINI_API_KEY detectada: {'Sim' if gemini_key else 'Não'}")
        
        if gemini_key:
            print(f"[INFO] Usando Engine: Google Gemini Flash (chave termina em ...{gemini_key[-4:]})")
            try:
                gemini_result = extract_with_gemini(image_bytes, gemini_key)
                if gemini_result:
                    print("[SUCCESS] Gemini extraiu dados com sucesso!")
                    return {
                        "success": True,
                        "extracted_fields": gemini_result,
                        "method": "GOOGLE_GEMINI_FLASH_AI"
                    }
                else:
                    print("[WARNING] Gemini retornou None (parsing/timeout?)")
            except Exception as gemini_error:
                print(f"[ERROR] Gemini Exception: {gemini_error}")
            
            # Se falhar no Gemini, cai pro fallback local
            print("[INFO] Caindo para Tesseract local...")
        else:
            print("[INFO] GEMINI_API_KEY não configurada. Usando Tesseract local.")

        # --- MODO LOCAL: TESSERACT + OPENCV ---
        # Obter versoes da imagem
        images = process_image_pipeline(image_bytes)
        
        # Estratégia de Tentativas (Ensemble)
        # Ordem de preferencia: Otsu (Mais limpo) -> Grayscale (Mais seguro) -> Adaptive (Agressivo) -> Original
        strategies = ['otsu', 'gray', 'adaptive', 'original']
        
        best_result = None
        best_score = -1
        last_text = ""
        
        for strategy in strategies:
            img_version = images[strategy]
            
            # Executar OCR
            # psm 3 = fully automatic. psm 6 = block of text
            text = pytesseract.image_to_string(img_version, lang='por', config='--psm 3')
            
            extracted = parse_document_text(text)
            
            # Calcular Score de Qualidade
            score = 0
            if extracted['cpf']: score += 3
            if extracted['nome_provavel']: score += 2
            if extracted['rg']: score += 1
            if extracted['data_nascimento']: score += 1
            if extracted['tipo_documento'] != 'DESCONHECIDO': score += 2
            
            print(f"Strategy {strategy}: Score {score}, Len {len(text)}")
            
            # Se achou CPF e Nome, é Ouro! Para tudo e retorna.
            if extracted['cpf'] and extracted['nome_provavel']:
                return {
                    "success": True,
                    "extracted_fields": extracted,
                    "method": f"PYTHON_{strategy.upper()}_GOLD"
                }
            
            # Senao, guarda o melhor resultado até agora
            if score > best_score:
                best_score = score
                best_result = extracted
                last_text = text
                
        # Se saiu do loop, retorna o "menos pior"
        return {
            "success": True,
            "extracted_fields": best_result,
            # "raw_text": last_text if len(last_text) < 500 else last_text[:500] + "...", 
            "method": "PYTHON_BEST_EFFORT"
        }
        
    except Exception as e:
        print(f"Erro: {str(e)}")
        return {
            "success": False,
            "error": str(e)
        }

@app.get("/")
async def serve_index():
    return FileResponse('public/index.html')
