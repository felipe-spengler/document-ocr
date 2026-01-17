const sharp = require('sharp');

// Pré-processamentos para melhorar OCR
async function optimizeImageForOCR(buffer) {
    try {
        // Sharp permite manipular a imagem
        return await sharp(buffer)
            .resize(2000, 2000, { // Aumentar resolução ajuda o Tesseract
                fit: 'inside',
                withoutEnlargement: false
            })
            .grayscale() // Remove cor (ruído)
            .normalize() // Melhora contraste
            .sharpen()   // Deixa bordas mais nítidas (texto)
            .threshold(160) // Binarização: Transforma em preto e branco puro (ajuda muito em doc amassado/sombreado)
            .toBuffer();
    } catch (error) {
        console.warn('Erro ao otimizar imagem, usando original:', error);
        return buffer;
    }
}

module.exports = { optimizeImageForOCR };
