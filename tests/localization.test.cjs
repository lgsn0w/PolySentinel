const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');

const source = fs.readFileSync(path.join(__dirname, '..', 'static', 'localization.js'), 'utf8');

function translator(language) {
    const window = {};
    const document = {
        documentElement: { lang: language },
        getElementById: () => ({ textContent: JSON.stringify({ LIVE: 'AO VIVO', partial: 'parcial', 'No investigation yet. Choose Investigate / refresh to start.': 'Ainda não há investigação.' }) })
    };
    vm.runInNewContext(source, { window, document });
    return window;
}

test('Portuguese translates dynamic statuses and leaves evidence inert', () => {
    const { translateUI: t, uiLocale } = translator('pt-BR');
    assert.equal(uiLocale, 'pt-BR');
    assert.equal(t('LIVE'), 'AO VIVO');
    assert.equal(t('Last Update: 10:20'), 'Última atualização: 10:20');
    assert.equal(t('3 of 42 observed edges'), '3 de 42 transferências observadas');
    assert.equal(t('BUY Yes'), 'COMPRA Sim');
    assert.equal(t('0.00000123456789'), '0.00000123456789');
    assert.equal(t('<img src=x onerror=alert(1)>'), '<img src=x onerror=alert(1)>');
    assert.match(t('No investigation yet. Choose Investigate / refresh to start. Last checked: 10:20'), /^Ainda não há investigação\. Última consulta:/);
});

test('English is unchanged and locale has an explicit fallback', () => {
    for (const language of ['en', 'unexpected']) {
        const { translateUI: t, uiLocale } = translator(language);
        assert.equal(uiLocale, 'en-US');
        assert.equal(t('LIVE'), 'LIVE');
        assert.equal(t('3 of 42 observed edges'), '3 of 42 observed edges');
    }
});
