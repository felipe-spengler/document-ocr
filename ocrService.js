const Tesseract = require('tesseract.js');
const pdf = require('pdf-parse');
const { parseDocumentText } = require('./regexUtils');
const { optimizeImageForOCR } = require('./imageUtils');

/**
 * Função Principal de Extração
 * @param {string} base64Input - input base64
 */
async function extractDataFromImage(base64Input) {
    let text = '';
    // Remover cabeçalhos comuns de base64 se existirem (para garantir buffer limpo)
    const cleanBase64 = base64Input.replace(/^data:(.*);base64,/, "");
    const buffer = Buffer.from(cleanBase64, 'base64');

    // Detectar se é PDF verificando a assinatura do arquivo (%PDF)
    // Isso funciona independente da extensão ou mime-type informado
    const fileHeader = buffer.toString('utf8', 0, 5);
    const isPdf = fileHeader.startsWith('%PDF-');

    if (isPdf) {
        console.log('📂 Arquivo detectado: PDF');
        try {
            const pdfData = await pdf(buffer);
            text = pdfData.text;

            // Verificação de Qualidade: O PDF tem texto selecionável?
            // Se o texto for muito curto, provavelmente é um PDF Scan (imagem encapsulada).
            if (!text || text.replace(/\s/g, '').length < 20) {
                console.warn('⚠️ PDF sem camada de texto detectado (Scan).');
                return {
                    success: false,
                    error: 'O PDF enviado parece ser uma imagem digitalizada (scanner) sem texto reconhecível. O sistema atual suporta apenas PDFs Digitais (com texto selecionável) ou Imagens diretas (JPG/PNG). Por favor, envie a imagem do documento.',
                    method: 'PDF_SCAN_FAIL'
                };
            }

            console.log('✅ Texto extraído nativamente do PDF (Alta Fidelidade).');
            const structuredData = parseDocumentText(text);
            return {
                success: true,
                raw_text: text,
                extracted_fields: structuredData,
                method: 'PDF_NATIVE_EXTRACTION' // Indica que leu direto do arquivo
            };

        } catch (e) {
            console.error('Erro ao ler PDF:', e);
            throw new Error('Falha ao processar arquivo PDF: ' + e.message);
        }
    }

    // Se não for PDF, segue fluxo de Imagem (OCR)
    console.log('🖼️  Arquivo detectado: Imagem. Iniciando fluxo de OCR inteligente...');

    // 1. Pré-processamento "Nível FIFA" (Limpeza e Contraste)
    const optimizedBuffer = await optimizeImageForOCR(buffer);

    // 2. OCR com Tesseract (Motor Neural)
    // Configurar path do cache para evitar erro de permissão no Docker
    const cachePath = process.env.TESSERACT_CACHE_PATH || '.';
    const worker = await Tesseract.createWorker('por', 1, {
        cachePath: cachePath,
        logger: m => console.log(m) // Opcional: ver progresso
    });

    // Configurações para melhor leitura de blocos de texto
    await worker.setParameters({
        tessedit_char_whitelist: '0123456789abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ.-/áéíóúÁÉÍÓÚãõÃÕâêôÂÊÔçÇ ',
        tessedit_pageseg_mode: '3', // Auto segmentation
    });

    const { data } = await worker.recognize(optimizedBuffer);
    text = data.text;
    await worker.terminate();

    // 3. Pós-processamento e Extração de Campos
    const structuredData = parseDocumentText(text);

    return {
        success: true,
        raw_text: text,
        extracted_fields: structuredData,
        method: 'IMAGE_OCR_AI' // Indica que usou Inteligência Artificial para ler
    };
}

module.exports = { extractDataFromImage };
