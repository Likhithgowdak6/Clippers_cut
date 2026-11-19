const rail = document.querySelector(".studio-rail nav");

if (rail && matchMedia("(hover: hover) and (pointer: fine)").matches) {
  const highlight = document.createElement("div");
  highlight.className = "nav-hover";
  highlight.setAttribute("aria-hidden", "true");
  rail.prepend(highlight);
  const hide = () => { highlight.style.opacity = "0"; };
  rail.addEventListener("pointerover", (event) => {
    const item = event.target.closest("a");
    if (!item || item.hasAttribute("aria-current")) {
      hide();
      return;
    }
    highlight.style.width = `${item.offsetWidth}px`;
    highlight.style.height = `${item.offsetHeight}px`;
    highlight.style.transform = `translate(${item.offsetLeft}px, ${item.offsetTop}px)`;
    highlight.style.opacity = "1";
  });
  rail.addEventListener("pointerleave", hide);
}
