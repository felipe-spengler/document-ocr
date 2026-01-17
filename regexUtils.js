/**
 * Utilitários para extrair padrões de documentos brasileiros (RG, CPF, CNH)
 */

function parseDocumentText(text) {
    // 1. Limpeza Inicial do Texto
    const safeText = text || '';
    // Normalizar quebras de linha e remover caracteres muito estranhos
    const cleanText = safeText
        .replace(/\r\n/g, '\n')
        .replace(/\|/g, 'I') // OCR confunde I com |
        .replace(/[^a-zA-Z0-9\s\/\.\-\(\)]/g, ' ') // Mantem apenas alfanumerico e pontuacao basica
        .replace(/\s+/g, ' '); // Remove espacos duplos

    const lines = safeText.split('\n')
        .map(l => l.trim())
        .filter(l => l.length > 2); // Linhas muito curtas sao lixo

    const result = {
        cpf: null,
        data_nascimento: null,
        rg: null,
        nome_provavel: null,
        tipo_documento: 'DESCONHECIDO'
    };

    // --- 1. Identificar Tipo de Doc ---
    const textUpper = cleanText.toUpperCase();
    if (textUpper.includes('HABILITACAO') || textUpper.includes('CONDUTOR') || textUpper.includes('CNH')) {
        result.tipo_documento = 'CNH';
    } else if (textUpper.includes('IDENTIDADE') || textUpper.includes('SSP') || textUpper.includes('SECRETARIA')) {
        result.tipo_documento = 'RG';
    }

    // --- 2. CPF (Fuzzy Logic) ---
    // Remove tudo que nao é numero pra tentar achar o padrao de 11 digitos
    // Mas cuidado pra nao pegar outros numeros.
    // Melhor usar Regex Flexivel: 3 digitos, separador opcional, etc.
    // Tenta achar padroes como 123.456.789-00 ou 123 456 789 00
    const cpfLoosePattern = /(\d{3})[\.\s]?(\d{3})[\.\s]?(\d{3})[-\s]?(\d{2})/;

    // Varre linhas procurando algo que pareça CPF
    for (const line of lines) {
        // Limpa a linha de letras comuns que o OCR confunde com números em campos numericos
        // Ex: O -> 0, B -> 8, S -> 5, I -> 1
        const lineNums = fuzzyNumberClean(line);
        const match = lineNums.match(cpfLoosePattern);
        if (match) {
            // Validar digitos verificadores poderia ser um passo extra, mas aqui só extraímos
            result.cpf = `${match[1]}.${match[2]}.${match[3]}-${match[4]}`;
            break;
        }
    }

    // --- 3. Data de Nascimento ---
    const datePattern = /\d{2}\/\d{2}\/\d{4}/;

    // Prioridade 1: Linha que tem "NASCIMENTO" ou "NASC"
    for (const line of lines) {
        const lineUp = line.toUpperCase();
        if (lineUp.includes('NASCIMENTO') || lineUp.includes('DATA NASC')) {
            const d = line.match(datePattern);
            if (d) {
                result.data_nascimento = d[0];
                break; // Achou na linha certa, para!
            }
        }
    }

    // Prioridade 2: Se não achou na label, tenta achar datas e exclui as que sabemos que NÃO são nascimento
    if (!result.data_nascimento) {
        let candidates = [];
        for (const line of lines) {
            const d = line.match(datePattern);
            if (d) {
                const lineUp = line.toUpperCase();
                // Se a linha tem palavras "proibidas" pra nascimento, ignora
                if (lineUp.includes('VALIDADE') || lineUp.includes('EXPEDICAO') || lineUp.includes('DOC') || lineUp.includes('PRIMEIRA')) {
                    continue;
                }
                candidates.push(d[0]);
            }
        }

        // Se sobrou datas, pega a mais antiga (assumindo que nasc < todas as outras)
        if (candidates.length > 0) {
            candidates.sort((a, b) => {
                const da = new Date(a.split('/').reverse().join('-'));
                const db = new Date(b.split('/').reverse().join('-'));
                return da - db;
            });
            result.data_nascimento = candidates[0];
        }
    }

    // --- 4. Nome ---
    // O nome é o inferno do OCR. Vamos melhorar a heuristica.
    const blacklist = ['REPUBLICA', 'FEDERATIVA', 'BRASIL', 'MINISTERIO', 'IDENTIDADE',
        'CARTEIRA', 'NACIONAL', 'HABILITACAO', 'DETRAN', 'ASSINATURA',
        'VALIDA', 'DATA', 'NOME', 'FILIACAO', 'DOCUMENTO', 'ESTADO',
        'SECRETARIA', 'CPF', 'GERAL', 'REGISTRO', 'LEI', 'LOCAL', 'VIA'];

    // Procura pela ancora "NOME"
    let nameFound = false;
    for (let i = 0; i < lines.length; i++) {
        const line = lines[i].toUpperCase().replace(/[^A-Z\s]/g, '').trim(); // Limpa lixo
        if (line === 'NOME' || line.startsWith('NOME ')) {
            // O nome deve estar na proxima linha
            if (i + 1 < lines.length) {
                const candidate = lines[i + 1];
                if (isValidName(candidate, blacklist)) {
                    result.nome_provavel = candidate;
                    nameFound = true;
                    break;
                }
            }
        }
    }

    // Heurística de Fallback para Nome (Linhas apenas letras maiusculas)
    if (!nameFound) {
        for (const line of lines) {
            const cleanLine = line.trim();
            // Ignora linhas curtas ou com numeros
            if (cleanLine.length < 5 || /\d/.test(cleanLine)) continue;

            // Ignora se tiver char estranho (indicativo de lixo de ocr: @ # $ %)
            if (/[^a-zA-Z\s\.]/.test(cleanLine)) continue;

            const upper = cleanLine.toUpperCase();
            // Ignora se for palavra da blacklist
            if (isBlacklisted(upper, blacklist)) continue;

            // Se passou por tudo isso, parece um nome
            result.nome_provavel = cleanLine;
            break;
        }
    }

    // --- 5. RG ---
    // Procura padrao de RG, ignorando o CPF ja encontrado
    const rgPattern = /\d{1,2}\.?\d{3}\.?\d{3}-?[\dX]/;
    if (!result.rg) {
        for (const line of lines) {
            const lineUp = line.toUpperCase();
            // Ignora linhas de CPF ou Data
            if (lineUp.includes('CPF') || /\d{2}\/\d{2}\/\d{4}/.test(line)) continue;

            const nums = fuzzyNumberClean(line);
            const match = nums.match(rgPattern);
            if (match) {
                const found = match[0];
                // Verifica se não é o proprio CPF
                const rawFound = found.replace(/\D/g, '');
                const rawCpf = result.cpf ? result.cpf.replace(/\D/g, '') : '99999999999';
                if (rawFound !== rawCpf && rawFound.length >= 5) { // RG costuma ter min 5 digitos
                    result.rg = found;
                    break;
                }
            }
        }
    }

    return result;
}

// Converte letras parecidas com numeros para numeros (Só usar onde esperamos numeros!)
function fuzzyNumberClean(text) {
    return text.toUpperCase()
        .replace(/O/g, '0')
        .replace(/I/g, '1')
        .replace(/L/g, '1')
        .replace(/S/g, '5')
        .replace(/B/g, '8')
        .replace(/A/g, '4') // As vezes acontece
        .replace(/G/g, '6');
}

function isBlacklisted(str, list) {
    return list.some(word => str.includes(word));
}

function isValidName(str, blacklist) {
    if (!str || str.length < 4) return false;
    if (/\d/.test(str)) return false; // Nomes nao tem numeros
    if (isBlacklisted(str.toUpperCase(), blacklist)) return false;
    return true;
}

module.exports = { parseDocumentText };
