from fastapi import FastAPI, UploadFile, File, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
import base64
import io
import pytesseract
from PIL import Image
from ocr_engine import process_image_cv2, parse_document_text

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
    return {"status": "Online", "backend": "Python/OpenCV"}



from ocr_engine import process_image_pipeline, parse_document_text

@app.post("/extract")
async def extract_data(request: ExtractRequest):
    try:
        # Limpar header base64
        if "," in request.image:
            header, encoded = request.image.split(",", 1)
        else:
            encoded = request.image
            
        image_bytes = base64.b64decode(encoded)
        
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
            # psm 3 = fully automatic. psm 6 = block of text (as vezes melhor pra cartoes cortados)
            # Vamos tentar psm 3 padrao.
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
            "raw_text": last_text if len(last_text) < 500 else last_text[:500] + "...",
            "method": "PYTHON_BEST_EFFORT"
        }
        
    except Exception as e:
        print(f"Erro: {str(e)}")
        return {
            "success": False,
            "error": str(e)
        }

# Truque para servir o index.html na raiz com FastAPI
from fastapi.responses import FileResponse
@app.get("/")
async def serve_index():
    return FileResponse('public/index.html')
