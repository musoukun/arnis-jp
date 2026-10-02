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
    return { ...(await fetchJpExtras(languageCode)), ...localization };
}

/**
 * arnis-jp: strings of the Japan extensions live in locales/jp/<lang>.json, outside the
 * upstream locale files (which must all share en-US's key set). English is the base and the
 * requested language, when it has a file there, overrides it. Never throws.
 * @param {string} languageCode - The language code to fetch
 * @returns {Promise<Object>} Extra localization strings (possibly empty)
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
    return lang === 'en' ? base : { ...base, ...(await load(lang)) };
}
