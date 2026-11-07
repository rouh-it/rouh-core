// Every write the page makes carries Django's CSRF token.
//
// Rouh has been a Django project since 23 September 2026, and Django refuses a
// POST, a DELETE or any other write that does not carry the token from the
// `rouh_csrftoken` cookie in an `X-CSRFToken` header: that is what stops
// another site from making the person's browser act on Rouh behind their back.
// The page makes a great many writes - the paperclip, the Gene therapy drawer, the
// Stop control, the task browser filing a task - so rather than have each one
// remember the header, this puts it on all of them, once, before anything else
// on the page runs. It changes nothing else about a request.
//
// Only for this site's own addresses, and only for writes. The cookie is read
// at the moment of each request rather than once, because signing in again in
// another tab gives the browser a new token, and a tab left open must use the
// new one.
(function () {
  'use strict';

  var HEADER = 'X-CSRFToken';
  var SAFE = /^(GET|HEAD|OPTIONS|TRACE)$/i;

  function token() {
    var found = /(?:^|;\s*)rouh_csrftoken=([^;]+)/.exec(document.cookie || '');
    return found ? decodeURIComponent(found[1]) : '';
  }

  function ours(url) {
    try {
      return new URL(url, location.href).origin === location.origin;
    } catch (e) {
      return false;
    }
  }

  var fetchFirst = window.fetch;
  if (fetchFirst) {
    window.fetch = function (input, init) {
      var isRequest = typeof Request !== 'undefined' && input instanceof Request;
      var method = (init && init.method) || (isRequest ? input.method : 'GET');
      var url = isRequest ? input.url : String(input);
      if (!SAFE.test(method) && ours(url)) {
        var t = token();
        if (t) {
          var headers = new Headers((init && init.headers) || (isRequest ? input.headers : undefined));
          if (!headers.has(HEADER)) headers.set(HEADER, t);
          init = Object.assign({}, init, { headers: headers });
        }
      }
      return fetchFirst.call(this, input, init);
    };
  }

  var open = XMLHttpRequest.prototype.open;
  var send = XMLHttpRequest.prototype.send;
  XMLHttpRequest.prototype.open = function (method, url) {
    this.rouhNeedsToken = !SAFE.test(String(method)) && ours(url);
    return open.apply(this, arguments);
  };
  XMLHttpRequest.prototype.send = function () {
    if (this.rouhNeedsToken) {
      var t = token();
      if (t) this.setRequestHeader(HEADER, t);
    }
    return send.apply(this, arguments);
  };
})();
