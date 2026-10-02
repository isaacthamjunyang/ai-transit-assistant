(function () {
  var theme = "";
  try {
    var saved = window.localStorage.getItem("bus-catch-theme");
    if (saved === "light" || saved === "dark") {
      theme = saved;
    }
  } catch (error) {
    theme = "";
  }
  if (theme !== "light" && theme !== "dark") {
    var dark = false;
    try {
      dark = window.matchMedia("(prefers-color-scheme: dark)").matches;
    } catch (error) {
      dark = false;
    }
    theme = dark ? "dark" : "light";
  }
  document.documentElement.setAttribute("data-theme", theme);

  window.applyThemeChoice = function (choice) {
    if (choice !== "light" && choice !== "dark") {
      return;
    }
    document.documentElement.setAttribute("data-theme", choice);
    try {
      window.localStorage.setItem("bus-catch-theme", choice);
    } catch (error) {
      return;
    }
  };
})();
