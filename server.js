const express = require('express');
const cors = require('cors');
const bodyParser = require('body-parser');
const { extractDataFromImage } = require('./ocrService');

const app = express();
const PORT = process.env.PORT || 3000;

// Middleware
app.use(cors());
// Aumentar o limite para aceitar imagens grandes em Base64
app.use(bodyParser.json({ limit: '50mb' }));
app.use(bodyParser.urlencoded({ limit: '50mb', extended: true }));

// Rota de Health Check
app.get('/', (req, res) => {
  res.send({ status: 'Online', message: 'API de Documentos ativa' });
});

// Endpoint principal para extração
app.post('/extract', async (req, res) => {
  try {
    const { image, type } = req.body; // image: base64 string, type: 'rg', 'cnh', 'cpf' (opcional, ajuda no parser)

    if (!image) {
      return res.status(400).json({ error: 'Nenhuma imagem fornecida (campo "image" deve conter string base64).' });
    }

    console.log('Recebendo solicitação de extração...');

    // Processar Documento
    const result = await extractDataFromImage(image);

    // Se o serviço retornou sucesso false (ex: PDF Scan), devolvemos status 422
    if (result.success === false) {
      return res.status(422).json(result);
    }

    // Retorna sucesso
    res.json(result);

  } catch (error) {
    console.error('Erro na extração:', error);
    res.status(500).json({
      success: false,
      error: 'Falha ao processar o documento.',
      details: error.message
    });
  }
});

app.listen(PORT, () => {
  console.log(`Servidor rodando na porta ${PORT}`);
});
