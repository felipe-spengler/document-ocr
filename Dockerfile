# Usar versão LTS do Node (Debian slim para ter glibc necessário pro Sharp/Tesseract se preciso)
FROM node:20-slim

# Instalar dependências de sistema necessárias para o Canvas/Sharp/Tesseract se houver fallback
# Embora tesseract.js seja WASM, ter as libs de imagem ajuda a compatibilidade
RUN apt-get update && apt-get install -y \
    python3 \
    build-essential \
    libcairo2-dev \
    libpango1.0-dev \
    libjpeg-dev \
    libgif-dev \
    librsvg2-dev \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copiar arquivos de dependência primeiro (cache layer)
COPY package*.json ./

# Instalar dependências (production flag ignora devDependencies)
RUN npm install --omit=dev

# Copiar o restante do código
COPY . .

# Criar pasta para cache do Tesseract e dar permissão (evita erro de permissão ao baixar lang data)
RUN mkdir -p .tesseract_cache && chmod 777 .tesseract_cache
ENV TESSERACT_CACHE_PATH=.tesseract_cache

# Expor a porta
EXPOSE 3000

# Comando de inicialização
CMD ["npm", "start"]
