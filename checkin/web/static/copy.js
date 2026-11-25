// The "Copy" buttons next to the text for agents: copy the text of the <pre> they sit with.
document.querySelectorAll("[data-copy]").forEach(function (button) {
  button.hidden = !navigator.clipboard;
  button.addEventListener("click", function () {
    var text = document.getElementById(button.dataset.copy).innerText.trim();
    navigator.clipboard.writeText(text).then(function () {
      var label = button.textContent;
      button.textContent = button.dataset.done || "Copied";
      setTimeout(function () { button.textContent = label; }, 1500);
    });
  });
});
