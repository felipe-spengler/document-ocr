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



@app.post("/extract")
async def extract_data(request: ExtractRequest):
    try:
        # Limpar header base64 se existir
        if "," in request.image:
            header, encoded = request.image.split(",", 1)
        else:
            encoded = request.image
            
        image_bytes = base64.b64decode(encoded)
        
        # Passo 1: Processamento de Imagem com OpenCV
        # Isso remove o fundo verde/colorido e deixa o texto preto no branco
        processed_img_array = process_image_cv2(image_bytes)
        
        # Passo 2: OCR com Tesseract
        # Config: --psm 3 (Auto Page Segment), por (Portugues)
        text = pytesseract.image_to_string(processed_img_array, lang='por', config='--psm 3')
        
        # Passo 3: Parser de Texto
        extracted = parse_document_text(text)
        
        return {
            "success": True,
            "extracted_fields": extracted,
            "raw_text": text, # Opcional, bom pra debug
            "method": "PYTHON_OPENCV_ADAPTIVE"
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
