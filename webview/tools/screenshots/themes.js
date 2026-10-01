/*
 * VS Code theme variables for the screenshot harness page.
 *
 * Only the colours the viewer stylesheet reads (21 keys), plus the few that VS Code's
 * default webview stylesheet in page.html reads (scrollbars, <kbd>, <code>). Values are
 * VS Code 1.139's Dark Modern (dark_modern.json), Light Modern (light_modern.json) and
 * Dark High Contrast (hc_black.json) from extensions/theme-defaults/themes, with the
 * colour-registry default for a key the theme file leaves out. Read on 2026-09-29.
 * Source: microsoft/vscode, MIT License, Copyright (c) Microsoft Corporation.
 *
 * VS Code injects each colour as --vscode-<id with dots as dashes> on <html>, and stamps
 * <body> with vscode-dark, vscode-light or vscode-high-contrast. A key whose value is
 * null for the theme type (contrastBorder outside high contrast) is not injected, so the
 * viewer's own fallback applies; those keys are left out of the table below.
 */
(function () {
  var FONTS = {
    darwin: { 'font-family': '-apple-system, BlinkMacSystemFont, sans-serif', 'editor-font-family': "Menlo, Monaco, 'Courier New', monospace", 'editor-font-size': '12px' },
    win32: { 'font-family': '"Segoe WPC", "Segoe UI", sans-serif', 'editor-font-family': "Consolas, 'Courier New', monospace", 'editor-font-size': '14px' },
    linux: { 'font-family': 'system-ui, "Ubuntu", "Droid Sans", sans-serif', 'editor-font-family': "'Droid Sans Mono', 'monospace', monospace", 'editor-font-size': '14px' },
  };
  var COMMON = { 'font-weight': 'normal', 'font-size': '13px', 'editor-font-weight': 'normal', 'text-link-decoration': 'none' };
  var THEMES = {
    'dark-modern': {
      label: 'Dark Modern', bodyClass: 'vscode-dark', kind: 'dark',
      colors: {
        'foreground': '#CCCCCC', 'descriptionForeground': '#9D9D9D', 'focusBorder': '#0078D4', 'widget.border': '#313131',
        'editor.background': '#1F1F1F', 'editor.foreground': '#CCCCCC', 'editorWidget.background': '#202020',
        'editorLineNumber.foreground': '#6E7681', 'editorError.foreground': '#F14C4C', 'editorWarning.foreground': '#CCA700',
        'editorInfo.foreground': '#59A4F9', 'charts.red': '#F14C4C', 'charts.yellow': '#CCA700', 'charts.blue': '#59A4F9',
        'textLink.foreground': '#4daafc', 'textLink.activeForeground': '#4daafc', 'list.hoverBackground': '#2A2D2E',
        'button.background': '#0078D4', 'button.foreground': '#FFFFFF',
        'scrollbarSlider.background': '#79797966', 'scrollbarSlider.hoverBackground': '#646464B3', 'scrollbarSlider.activeBackground': '#BFBFBF66',
        'keybindingLabel.background': '#8080802B', 'keybindingLabel.foreground': '#CCCCCC', 'keybindingLabel.border': '#33333399',
        'keybindingLabel.bottomBorder': '#44444499', 'widget.shadow': '#0000005C', 'textPreformat.foreground': '#D0D0D0',
        'textPreformat.background': '#3C3C3C', 'textBlockQuote.background': '#2B2B2B', 'textBlockQuote.border': '#616161',
      },
    },
    'light-modern': {
      label: 'Light Modern', bodyClass: 'vscode-light', kind: 'light',
      colors: {
        'foreground': '#3B3B3B', 'descriptionForeground': '#3B3B3B', 'focusBorder': '#005FB8', 'widget.border': '#E5E5E5',
        'editor.background': '#FFFFFF', 'editor.foreground': '#3B3B3B', 'editorWidget.background': '#F8F8F8',
        'editorLineNumber.foreground': '#6E7681', 'editorError.foreground': '#E51400', 'editorWarning.foreground': '#BF8803',
        'editorInfo.foreground': '#0063D3', 'charts.red': '#E51400', 'charts.yellow': '#BF8803', 'charts.blue': '#0063D3',
        'textLink.foreground': '#005FB8', 'textLink.activeForeground': '#005FB8', 'list.hoverBackground': '#F2F2F2',
        'button.background': '#005FB8', 'button.foreground': '#FFFFFF',
        'scrollbarSlider.background': '#64646466', 'scrollbarSlider.hoverBackground': '#646464B3', 'scrollbarSlider.activeBackground': '#00000099',
        'keybindingLabel.background': '#DDDDDD66', 'keybindingLabel.foreground': '#3B3B3B', 'keybindingLabel.border': '#CCCCCC66',
        'keybindingLabel.bottomBorder': '#BBBBBB66', 'widget.shadow': '#00000029', 'textPreformat.foreground': '#3B3B3B',
        'textPreformat.background': '#0000001F', 'textBlockQuote.background': '#F8F8F8', 'textBlockQuote.border': '#E5E5E5',
      },
    },
    'hc-dark': {
      label: 'Dark High Contrast', bodyClass: 'vscode-high-contrast', kind: 'hc',
      colors: {
        'foreground': '#FFFFFF', 'descriptionForeground': '#FFFFFFB2', 'focusBorder': '#F38518', 'contrastBorder': '#6FC3DF',
        'widget.border': '#6FC3DF', 'editor.background': '#000000', 'editor.foreground': '#FFFFFF', 'editorWidget.background': '#0C141F',
        'editorLineNumber.foreground': '#FFFFFF', 'editorError.foreground': '#F48771', 'editorWarning.foreground': '#FFD370',
        'editorInfo.foreground': '#59A4F9', 'charts.red': '#F48771', 'charts.yellow': '#FFD370', 'charts.blue': '#59A4F9',
        'textLink.foreground': '#21A6FF', 'textLink.activeForeground': '#21A6FF', 'list.hoverBackground': '#FFFFFF1A',
        'button.background': '#000000', 'button.foreground': '#FFFFFF',
        'scrollbarSlider.background': '#6FC3DF99', 'scrollbarSlider.hoverBackground': '#6FC3DFCC', 'scrollbarSlider.activeBackground': '#6FC3DF',
        'keybindingLabel.background': '#00000000', 'keybindingLabel.foreground': '#FFFFFF', 'keybindingLabel.border': '#6FC3DF',
        'keybindingLabel.bottomBorder': '#6FC3DF', 'textPreformat.foreground': '#FFFFFF', 'textBlockQuote.border': '#FFFFFF',
      },
    },
  };
  function apply(name, platform) {
    var theme = THEMES[name];
    if (!theme) throw new Error('unknown theme ' + name);
    var style = document.documentElement.style;
    var fonts = FONTS[platform] || FONTS.linux;
    var set = function (table) { Object.keys(table).forEach(function (k) { style.setProperty('--vscode-' + k, table[k]); }); };
    set(COMMON);
    set(fonts);
    Object.keys(theme.colors).forEach(function (k) { style.setProperty('--vscode-' + k.replace(/\./g, '-'), theme.colors[k]); });
    // VS Code paints the editor background behind the webview frame.
    style.background = theme.colors['editor.background'];
    var body = document.body;
    body.className = theme.bodyClass;
    body.setAttribute('data-vscode-theme-kind', theme.bodyClass);
    body.setAttribute('data-vscode-theme-name', theme.label);
    return theme;
  }
  window.MLVIEW_SCREENSHOT_THEMES = Object.keys(THEMES);
  window.MLVIEW_SCREENSHOT_APPLY_THEME = apply;
})();
