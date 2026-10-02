/* Minimal service worker. It exists only so phones can show local notifications and handle taps.
   No fetch handler, no cache, no push, no background sync, no storage. */

self.addEventListener("install", function () {
  self.skipWaiting();
});

self.addEventListener("activate", function (event) {
  event.waitUntil(self.clients.claim());
});

self.addEventListener("notificationclick", function (event) {
  event.notification.close();
  event.waitUntil(
    self.clients.matchAll({ type: "window", includeUncontrolled: true }).then(function (windows) {
      for (var i = 0; i < windows.length; i++) {
        if ("focus" in windows[i]) {
          windows[i].postMessage({ type: "transfer-alert" });
          return windows[i].focus();
        }
      }
      return self.clients.openWindow("/");
    })
  );
});
