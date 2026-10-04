const DEFAULT_LOCALE_PATH = `./locales/en.json`;

/**
 * Checks if a JSON response is invalid or falls back to HTML
 * @param {Response} response - The fetch response object
 * @returns {boolean} True if the response is invalid JSON
 */
export function invalidJSON(response) {
    return !response.ok || response.headers.get("Content-Type") === "text/html";
}

/**
 * Fetches a specific language file
 * @param {string} languageCode - The language code to fetch
 * @returns {Promise<Object>} The localization JSON object
 */
export async function fetchLanguage(languageCode) {

    let response = await fetch(`./locales/${languageCode}.json`);

    // Try with only first part of language code if not found
    if (invalidJSON(response)) {
        response = await fetch(`./locales/${languageCode.split('-')[0]}.json`);

    // Fallback to default English localization
        if (invalidJSON(response)) {
            response = await fetch(DEFAULT_LOCALE_PATH);
        }
    }

    const localization = await response.json();
    const extras = await fetchJpExtras(languageCode);
    return { ...extras.base, ...localization, ...extras.lang };
}

/**
 * arnis-jp: strings of the Japan extensions live in locales/jp/<lang>.json, outside the
 * upstream locale files (which must all share en-US's key set). `base` (English) only fills
 * keys upstream lacks; `lang` (the requested language) also overrides upstream strings, so
 * jp/ja.json can reword an upstream label without touching ja.json. Never throws.
 * @param {string} languageCode - The language code to fetch
 * @returns {Promise<{base: Object, lang: Object}>} Extra localization strings (possibly empty)
 */
async function fetchJpExtras(languageCode) {
    const load = async (code) => {
        try {
            const r = await fetch(`./locales/jp/${code}.json`);
            if (invalidJSON(r)) return {};
            return await r.json();
        } catch (_) {
            return {};
        }
    };
    const base = await load('en');
    const lang = languageCode.split('-')[0];
    return { base, lang: lang === 'en' ? {} : await load(lang) };
}
