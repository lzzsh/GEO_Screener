function tr(source, values = {}) {
  if (source === null || source === undefined) return '';
  const text = String(source);
  if (text.startsWith('PDF: ')) return 'PDF: ' + tr(text.slice(5));
  const publicationPrefix = 'Verify the associated publication and upload the article; PMID: ';
  if (text.startsWith(publicationPrefix)) return (window.uiMessages?.[publicationPrefix] ?? publicationPrefix) + text.slice(publicationPrefix.length);
  if (window.uiLang === 'en' && text.startsWith('无法标记已复核：')) {
    return 'Cannot mark reviewed: ' + text.slice(8).split('；').map(part=>tr(part)).join('; ');
  }
  if (window.uiLang === 'en' && /^第 \d+ 行：/.test(text)) {
    const [, row, issue] = text.match(/^第 (\d+) 行：(.*)$/s);
    return 'Row ' + row + ': ' + tr(issue);
  }
  if (window.uiLang === 'en' && !window.uiMessages?.[text]) {
    const patterns = [
      [/^(.+) 的取值不合法$/, '$1 has an invalid value'],
      [/^(.+) 缺失$/, '$1 is missing'],
      [/^(.+) 应为非负数或 NA$/, '$1 must be non-negative or NA'],
      [/^(.+) 无法按 time_unit 解释，或位于 Day 0 之前$/, '$1 cannot be interpreted with time_unit, or precedes Day 0'],
      [/^GSM (.+) 不属于所选来源$/, 'GSM $1 does not belong to the selected source'],
      [/^第 (\d+) 行缺少 values 对象$/, 'Row $1 has no values object'],
    ];
    for (const [pattern, replacement] of patterns) {
      if (pattern.test(text)) return text.replace(pattern, replacement);
    }
  }
  const translated = window.uiMessages?.[text] ?? text;
  return translated.replace(/\{(\w+)\}/g, (match, key) => values[key] ?? match);
}
function setUiLanguage(language) {
  if (!['zh', 'en'].includes(language) || language === window.uiLang) return;
  if (!window.dispatchEvent(new CustomEvent('ui:language-change', {cancelable:true}))) return;
  document.cookie = 'geo_ui_lang=' + language + '; Path=/; Max-Age=31536000; SameSite=Lax';
  window.location.reload();
}
