/**
 * Utilitários para extrair padrões de documentos brasileiros (RG, CPF, CNH)
 */

function parseDocumentText(text) {
    // Melhorar limpeza: substituir múltiplos espaços por um, remover caracteres estranhos resultantes de OCR ruim
    const cleanText = text
        .replace(/\r\n/g, '\n')
        .replace(/\|/g, 'I') // OCR confunde I com |
        .replace(/cleanText/g, '') // remove artifact
        .replace(/[^\x20-\x7E\xA0-\xFF\n]/g, '') // Remove caracteres não imprimíveis bizarros
        .trim();

    const lines = cleanText.split('\n').map(l => l.trim()).filter(l => l.length > 0);

    const result = {
        cpf: null,
        data_nascimento: null,
        rg: null,
        nome_provavel: null,
        tipo_documento: 'DESCONHECIDO'
    };

    // --- Patterns ---
    const cpfPattern = /\d{3}\.?\d{3}\.?\d{3}-?\d{2}/;
    // Data: DD/MM/AAAA. Tenta pegar casos com erro de OCR ex: 01/01/199o
    const datePattern = /\d{2}\/\d{2}\/\d{4}/g;

    // --- 1. Identificar Tipo de Doc (Heurística) ---
    const textUpper = cleanText.toUpperCase();
    if (textUpper.includes('HABILITACAO') || textUpper.includes('CONDUTOR')) {
        result.tipo_documento = 'CNH';
    } else if (textUpper.includes('IDENTIDADE') || textUpper.includes('SSP') || textUpper.includes('SECRETARIA')) {
        result.tipo_documento = 'RG';
    }

    // --- 2. CPF ---
    const cpfMatch = cleanText.match(cpfPattern);
    if (cpfMatch) {
        result.cpf = cpfMatch[0].replace(/[^\d]/g, '').replace(/(\d{3})(\d{3})(\d{3})(\d{2})/, '$1.$2.$3-$4');
    }

    // --- 3. Data de Nascimento ---
    // Estratégia: Procurar a label "Nascimento" e pegar a data próxima
    let foundDob = false;
    for (let i = 0; i < lines.length; i++) {
        const line = lines[i].toUpperCase();
        if (line.includes('NASCIMENTO') || line.includes('NASC')) {
            // Tenta achar data na mesma linha
            const d = line.match(datePattern);
            if (d) {
                result.data_nascimento = d[0];
                foundDob = true;
                break;
            }
            // Tenta achar na proxima linha
            if (i + 1 < lines.length) {
                const d2 = lines[i + 1].match(datePattern);
                if (d2) {
                    result.data_nascimento = d2[0];
                    foundDob = true;
                    break;
                }
            }
        }
    }
    // Fallback Data: Se não achou na label, pega a data mais antiga do documento (Geralmente nasc é mais antigo que expedição)
    if (!foundDob) {
        const allDates = cleanText.match(datePattern);
        if (allDates && allDates.length > 0) {
            // Parse dates objects
            const parsedDates = allDates.map(d => {
                const parts = d.split('/');
                return { str: d, date: new Date(`${parts[2]}-${parts[1]}-${parts[0]}`) };
            }).filter(d => !isNaN(d.date));

            // Ordenar por data
            parsedDates.sort((a, b) => a.date - b.date);
            if (parsedDates.length > 0) {
                // A primeira data costuma ser nascimento (anos atrás)
                result.data_nascimento = parsedDates[0].str;
            }
        }
    }

    // --- 4. Nome ---
    // Estratégia CNH: Nome está na linho logo abaixo de "NOME"
    // Estratégia RG: Nome está isolado

    let nameCandidate = null;
    const blacklist = ['REPUBLICA', 'FEDERATIVA', 'BRASIL', 'MINISTERIO', 'IDENTIDADE',
        'CARTEIRA', 'NACIONAL', 'HABILITACAO', 'DETRAN', 'ASSINATURA',
        'VALIDA', 'DATA', 'NOME', 'FILIACAO', 'DOCUMENTO', 'ESTADO',
        'SECRETARIA', 'CPF', 'GERAL', 'REGISTRO', 'LEI', 'LOCAL'];

    // Tentativa por âncora "NOME" (comum em CNH)
    const nomeIdx = lines.findIndex(l => l.toUpperCase() === 'NOME' || l.toUpperCase().startsWith('NOME '));
    if (nomeIdx !== -1 && nomeIdx + 1 < lines.length) {
        nameCandidate = lines[nomeIdx + 1];
    }

    // Se falhou, heurística de linha com apenas letras maiúsculas e maior que X chars
    if (!nameCandidate || isBlacklisted(nameCandidate, blacklist)) {
        // Percorrer linhas procurando nome provavel
        // Nomes em docs costumam ser:
        // - Letras Maiúsculas
        // - Sem numeros
        // - Tamanho razoavel (> 3 palavras ajuda a filtrar headers, mas as vezes nome é curto)

        for (const line of lines) {
            if (line.length < 5) continue;
            if (/\d/.test(line)) continue; // Tem numero? nao é nome

            // Verifica palavras bloqueadas
            if (isBlacklisted(line, blacklist)) continue;

            const words = line.split(/\s+/);
            if (words.length >= 2) {
                // Achamos uma linha com 2+ palavras, sem numeros, maiuscula e sem blacklist
                // Grande chance de ser o nome
                nameCandidate = line;
                break;
            }
        }
    }

    if (nameCandidate) result.nome_provavel = nameCandidate;

    // --- 5. RG ---
    // Tenta pegar o que não é CPF
    // RG Geralmente tem pontos, mas formato varia muito por estado.
    // Procura palavra RG ou REGISTRO GERAL e pega numeros proximos? Dificil no OCR.
    // Melhor pegar regex genérico de "número formatado" que não seja o CPF já extraído.

    // Regex generica para formatos de RG: X.XXX.XXX-X ou XX.XXX.XXX-X ...
    const rgLoosePattern = /\d{1,2}\.?\d{3}\.?\d{3}-?[\dX]/g;
    const potentialRGs = cleanText.match(rgLoosePattern);

    if (potentialRGs) {
        // Filtrar o que é igual ao CPF extraido
        const cleanCPF = result.cpf ? result.cpf.replace(/\D/g, '') : '99999999999';

        const validRGs = potentialRGs.filter(r => {
            const nums = r.replace(/\D/g, '');
            // Ignora se for igual ao CPF
            if (nums === cleanCPF) return false;
            // Ignora se for muito pequeno ou muito grande (RG tem media 8 a 10 digitos?)
            if (nums.length < 5 || nums.length > 13) return false;
            return true;
        });

        if (validRGs.length > 0) {
            result.rg = validRGs[0];
        }
    }

    return result;
}

function isBlacklisted(str, list) {
    if (!str) return true;
    const upper = str.toUpperCase();
    return list.some(word => upper.includes(word));
}

module.exports = { parseDocumentText };
