/*
 * The VS Code side of the webview, for the screenshot harness page.
 *
 * Runs at the top of <body>, before the viewer bundle and the panel bootstrap, where VS Code
 * has already stamped the body classes and injected acquireVsCodeApi. When the bootstrap posts
 * `ready`, the page fetches the frames capture.mjs prepared for this load (init, workflow, and
 * for a stale state the stale and workflowError frames) and delivers them one by one as
 * window `message` events, the way VS Code delivers webview.postMessage. Nothing answers the
 * viewer's own requests: an openLocation, copy or export is only recorded in window.__uiPosts.
 */
(function () {
  var query = new URLSearchParams(location.search);
  window.MLVIEW_SCREENSHOT_APPLY_THEME(query.get('theme') || 'dark-modern', query.get('platform') || 'linux');
  var posts = (window.__uiPosts = []);
  window.__framesDelivered = null;
  var state = null;
  var acquired = false;

  function deliverFrames() {
    fetch('/frames.json?load=' + encodeURIComponent(query.get('load') || ''), { cache: 'no-store' })
      .then(function (response) { return response.json(); })
      .then(function (frames) {
        var i = 0;
        (function next() {
          if (i >= frames.length) { window.__framesDelivered = frames.map(function (f) { return f.type; }); return; }
          window.dispatchEvent(new MessageEvent('message', { data: frames[i++] }));
          setTimeout(next, 0);
        })();
      });
  }

  window.acquireVsCodeApi = function () {
    if (acquired) throw new Error('An instance of the VS Code API has already been acquired');
    acquired = true;
    return Object.freeze({
      postMessage: function (message) {
        var copy = JSON.parse(JSON.stringify(message));
        posts.push(copy);
        if (copy && copy.type === 'ready') deliverFrames();
      },
      setState: function (value) { state = value; return value; },
      getState: function () { return state; },
    });
  };
})();
