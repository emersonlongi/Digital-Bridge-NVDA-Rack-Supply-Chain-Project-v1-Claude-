// Single source of truth for the site navigation.
// Add or rename a tab here once and every page picks it up on next load.
(function () {
  var pages = [
    ["index.html",        "Revenue Index"],
    ["supplychain.html",  "Winning-Content Map"],
    ["scoreboard.html",   "Live Scoreboard"],
    ["news.html",         "Supply-Chain News"],
    ["readthrough.html",  "Read-Through"],
    ["power.html",        "Grid Demand Pulse"]
    ["gw.html",           "GW in Transit"]
  ];
  var here = (location.pathname.split("/").pop() || "index.html").toLowerCase();
  if (here === "") here = "index.html";
  var nav = '<nav class="nav">';
  for (var i = 0; i < pages.length; i++) {
    var active = (pages[i][0] === here) ? ' class="active"' : '';
    nav += '<a href="' + pages[i][0] + '"' + active + '>' + pages[i][1] + '</a>';
  }
  nav += '</nav>';
  var slot = document.getElementById("nav");
  if (slot) slot.outerHTML = nav;
})();
