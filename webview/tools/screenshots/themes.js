/*
 * VS Code theme variables for the screenshot harness page.
 *
 * Only the colours the viewer stylesheet reads (21 keys), plus the few that VS Code's
 * default webview stylesheet in page.html reads (scrollbars, <kbd>, <code>). Values are
 * VS Code 1.139's Dark Modern (dark_modern.json), Light Modern (light_modern.json) and
 * Dark High Contrast (hc_black.json) from extensions/theme-defaults/themes, with the
 * colour-registry default for a key the theme file leaves out. Read on 2026-09-29.
 * Viewer M4 added Dark+ (dark_plus.json over dark_vs.json), Light+ (light_plus.json over
 * light_vs.json), Light High Contrast (hc_light.json, which sets no colour of its own), and
 * Dark 2026 and Light 2026 (2026-dark.json, 2026-light.json; VS Code 1.139's default dark and
 * light themes), the same way, read on 2026-10-03. A colour the registry derives with alpha
 * (descriptionForeground is the foreground at 70% in Dark+ and both High Contrast themes) is
 * written as #RRGGBBAA; VS Code injects it as rgba(). For Light High Contrast VS Code stamps
 * <body> with both vscode-high-contrast-light and vscode-high-contrast.
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
    'dark-plus': {
      label: 'Dark+', bodyClass: 'vscode-dark', kind: 'dark',
      colors: {
        'foreground': '#CCCCCC', 'descriptionForeground': '#CCCCCCB2', 'focusBorder': '#007FD4', 'widget.border': '#303031',
        'editor.background': '#1E1E1E', 'editor.foreground': '#D4D4D4', 'editorWidget.background': '#252526',
        'editorLineNumber.foreground': '#858585', 'editorError.foreground': '#F14C4C', 'editorWarning.foreground': '#CCA700',
        'editorInfo.foreground': '#59A4F9', 'charts.red': '#F14C4C', 'charts.yellow': '#CCA700', 'charts.blue': '#59A4F9',
        'textLink.foreground': '#3794FF', 'textLink.activeForeground': '#3794FF', 'list.hoverBackground': '#2A2D2E', 'button.background': '#0E639C',
        'button.foreground': '#FFFFFF', 'scrollbarSlider.background': '#79797966', 'scrollbarSlider.hoverBackground': '#646464B3',
        'scrollbarSlider.activeBackground': '#BFBFBF66', 'keybindingLabel.background': '#8080802B', 'keybindingLabel.foreground': '#CCCCCC',
        'keybindingLabel.border': '#33333399', 'keybindingLabel.bottomBorder': '#44444499', 'widget.shadow': '#0000005C',
        'textPreformat.foreground': '#D7BA7D', 'textPreformat.background': '#FFFFFF1A', 'textBlockQuote.background': '#222222',
        'textBlockQuote.border': '#007ACC80'
      },
    },
    'light-plus': {
      label: 'Light+', bodyClass: 'vscode-light', kind: 'light',
      colors: {
        'foreground': '#616161', 'descriptionForeground': '#717171', 'focusBorder': '#0090F1', 'widget.border': '#D4D4D4',
        'editor.background': '#FFFFFF', 'editor.foreground': '#000000', 'editorWidget.background': '#F3F3F3',
        'editorLineNumber.foreground': '#237893', 'editorError.foreground': '#E51400', 'editorWarning.foreground': '#BF8803',
        'editorInfo.foreground': '#0063D3', 'charts.red': '#E51400', 'charts.yellow': '#BF8803', 'charts.blue': '#0063D3',
        'textLink.foreground': '#006AB1', 'textLink.activeForeground': '#006AB1', 'list.hoverBackground': '#E8E8E8', 'button.background': '#007ACC',
        'button.foreground': '#FFFFFF', 'scrollbarSlider.background': '#64646466', 'scrollbarSlider.hoverBackground': '#646464B3',
        'scrollbarSlider.activeBackground': '#00000099', 'keybindingLabel.background': '#DDDDDD66', 'keybindingLabel.foreground': '#555555',
        'keybindingLabel.border': '#CCCCCC66', 'keybindingLabel.bottomBorder': '#BBBBBB66', 'widget.shadow': '#00000029',
        'textPreformat.foreground': '#A31515', 'textPreformat.background': '#0000001A', 'textBlockQuote.background': '#F2F2F2',
        'textBlockQuote.border': '#007ACC80'
      },
    },
    'hc-light': {
      label: 'Light High Contrast', bodyClass: 'vscode-high-contrast-light vscode-high-contrast', kind: 'hc',
      colors: {
        'foreground': '#292929', 'descriptionForeground': '#292929B2', 'focusBorder': '#006BBD', 'contrastBorder': '#0F4A85',
        'widget.border': '#0F4A85', 'editor.background': '#FFFFFF', 'editor.foreground': '#292929', 'editorWidget.background': '#FFFFFF',
        'editorLineNumber.foreground': '#292929', 'editorError.foreground': '#B5200D', 'editorWarning.foreground': '#895503',
        'editorInfo.foreground': '#0063D3', 'charts.red': '#B5200D', 'charts.yellow': '#895503', 'charts.blue': '#0063D3',
        'textLink.foreground': '#0F4A85', 'textLink.activeForeground': '#0F4A85', 'list.hoverBackground': '#0F4A851A', 'button.background': '#0F4A85',
        'button.foreground': '#FFFFFF', 'scrollbarSlider.background': '#0F4A8566', 'scrollbarSlider.hoverBackground': '#0F4A85CC',
        'scrollbarSlider.activeBackground': '#0F4A85', 'keybindingLabel.background': '#00000000', 'keybindingLabel.foreground': '#292929',
        'keybindingLabel.border': '#0F4A85', 'keybindingLabel.bottomBorder': '#292929', 'textPreformat.foreground': '#FFFFFF',
        'textPreformat.background': '#09345F', 'textBlockQuote.background': '#F2F2F2', 'textBlockQuote.border': '#292929'
      },
    },
    'dark-2026': {
      label: 'Dark 2026', bodyClass: 'vscode-dark', kind: 'dark',
      colors: {
        'foreground': '#BFBFBF', 'descriptionForeground': '#8C8C8C', 'focusBorder': '#3994BCB3', 'widget.border': '#2A2B2C',
        'editor.background': '#121314', 'editor.foreground': '#BBBEBF', 'editorWidget.background': '#202122',
        'editorLineNumber.foreground': '#858889', 'editorError.foreground': '#F14C4C', 'editorWarning.foreground': '#CCA700',
        'editorInfo.foreground': '#59A4F9', 'charts.red': '#EF8773', 'charts.yellow': '#E0B97F', 'charts.blue': '#57A3F8',
        'textLink.foreground': '#48A0C7', 'textLink.activeForeground': '#53A5CA', 'list.hoverBackground': '#FFFFFF14', 'button.background': '#297AA0',
        'button.foreground': '#FFFFFF', 'scrollbarSlider.background': '#A8A9AA85', 'scrollbarSlider.hoverBackground': '#A8A9AA90',
        'scrollbarSlider.activeBackground': '#A8A9AA9C', 'keybindingLabel.background': '#8080802B', 'keybindingLabel.foreground': '#CCCCCC',
        'keybindingLabel.border': '#33333399', 'keybindingLabel.bottomBorder': '#44444499', 'widget.shadow': '#0000005C',
        'textPreformat.foreground': '#8C8C8C', 'textPreformat.background': '#262626', 'textBlockQuote.background': '#242526',
        'textBlockQuote.border': '#2A2B2C'
      },
    },
    'light-2026': {
      label: 'Light 2026', bodyClass: 'vscode-light', kind: 'light',
      colors: {
        'foreground': '#202020', 'descriptionForeground': '#606060', 'focusBorder': '#0069CC', 'widget.border': '#E2E2E5',
        'editor.background': '#FFFFFF', 'editor.foreground': '#202020', 'editorWidget.background': '#FAFAFD',
        'editorLineNumber.foreground': '#606060', 'editorError.foreground': '#E51400', 'editorWarning.foreground': '#BF8803',
        'editorInfo.foreground': '#0063D3', 'charts.red': '#AD0707', 'charts.yellow': '#667309', 'charts.blue': '#1A5CFF',
        'textLink.foreground': '#0069CC', 'textLink.activeForeground': '#0069CC', 'list.hoverBackground': '#00000014', 'button.background': '#0069CC',
        'button.foreground': '#FFFFFF', 'scrollbarSlider.background': '#646464C0', 'scrollbarSlider.hoverBackground': '#646464D0',
        'scrollbarSlider.activeBackground': '#646464E0', 'keybindingLabel.background': '#DDDDDD66', 'keybindingLabel.foreground': '#3B3B3B',
        'keybindingLabel.border': '#CCCCCC66', 'keybindingLabel.bottomBorder': '#BBBBBB66', 'widget.shadow': '#00000000',
        'textPreformat.foreground': '#606060', 'textPreformat.background': '#ECECEC', 'textBlockQuote.background': '#EAEAEA',
        'textBlockQuote.border': '#F0F1F2'
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
    body.setAttribute('data-vscode-theme-kind', theme.bodyClass.split(' ')[0]);
    body.setAttribute('data-vscode-theme-name', theme.label);
    return theme;
  }
  window.MLVIEW_SCREENSHOT_THEMES = Object.keys(THEMES);
  window.MLVIEW_SCREENSHOT_APPLY_THEME = apply;
})();
