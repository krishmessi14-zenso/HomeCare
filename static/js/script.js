// Confirmation dialogs for destructive forms: <form data-confirm="Are you sure?">
document.addEventListener('submit', function (e) {
  var msg = e.target.getAttribute('data-confirm');
  if (msg && !window.confirm(msg)) { e.preventDefault(); }
});
// Auto-dismiss flash messages after 8 seconds
window.addEventListener('load', function () {
  setTimeout(function () {
    document.querySelectorAll('.alert-dismissible.auto-dismiss').forEach(function (el) {
      if (window.bootstrap) { bootstrap.Alert.getOrCreateInstance(el).close(); }
    });
  }, 8000);
});
