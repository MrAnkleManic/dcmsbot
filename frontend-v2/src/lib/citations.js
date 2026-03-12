/**
 * Parse citation markers from answer text and return segments:
 * either plain text or citation references.
 *
 * Handles:
 *  - Single citations: [C001], [1]
 *  - Comma-separated lists: [C001, C004], [C001, C005, C007]
 */
export function parseCitations(text) {
  if (!text) return [];

  const parts = [];
  // Match bracketed citation groups: [C001], [C001, C004], [1], [1, 3, 5] etc.
  const regex = /\[C?(\d+)(?:\s*,\s*C?(\d+))*\]/g;
  let lastIndex = 0;
  let match;

  while ((match = regex.exec(text)) !== null) {
    if (match.index > lastIndex) {
      parts.push({ type: 'text', value: text.slice(lastIndex, match.index) });
    }

    // Extract all citation IDs from the matched group (e.g. "[C001, C005, C007]")
    const inner = match[0].slice(1, -1); // strip brackets
    const ids = inner.split(/\s*,\s*/).map(s => s.replace(/^C/, ''));
    for (const id of ids) {
      parts.push({ type: 'citation', id });
    }

    lastIndex = regex.lastIndex;
  }

  if (lastIndex < text.length) {
    parts.push({ type: 'text', value: text.slice(lastIndex) });
  }

  return parts;
}

/** Convert citation number to superscript unicode */
export function toSuperscript(n) {
  const superDigits = { 0: '\u2070', 1: '\u00B9', 2: '\u00B2', 3: '\u00B3', 4: '\u2074', 5: '\u2075', 6: '\u2076', 7: '\u2077', 8: '\u2078', 9: '\u2079' };
  return String(n).split('').map(d => superDigits[d] || d).join('');
}
