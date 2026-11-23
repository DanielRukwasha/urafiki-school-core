"use strict";
document.addEventListener("submit", event => {
  const text = event.target.dataset.confirm;
  if (text && !window.confirm(text)) event.preventDefault();
});
