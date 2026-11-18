(function () {
  "use strict";

  function element(tag, className, text) {
    var node = document.createElement(tag);
    if (className) node.className = className;
    if (text !== undefined && text !== null) node.textContent = String(text);
    return node;
  }

  function renderTable(table) {
    var fragment = document.createDocumentFragment();
    fragment.appendChild(element("h3", "", table.title));
    var wrap = element("div", "table-wrap");
    var tableNode = element("table");
    var thead = element("thead");
    var headerRow = element("tr");
    (table.headers || []).forEach(function (header) {
      headerRow.appendChild(element("th", "", header));
    });
    thead.appendChild(headerRow);
    tableNode.appendChild(thead);

    var tbody = element("tbody");
    (table.rows || []).forEach(function (row) {
      var rowNode = element("tr");
      row.forEach(function (cell, index) {
        var cellNode = element("td", "", cell);
        cellNode.dataset.label = (table.headers || [])[index] || "";
        rowNode.appendChild(cellNode);
      });
      tbody.appendChild(rowNode);
    });
    tableNode.appendChild(tbody);
    wrap.appendChild(tableNode);
    fragment.appendChild(wrap);
    return fragment;
  }

  function render(report) {
    var root = document.getElementById("report-root");
    root.textContent = "";
    document.title = report.title + " · " + report.date;

    var header = element("header");
    header.appendChild(element("div", "muted", "团队战斗日志审计"));
    header.appendChild(element("h1", "", report.title));
    header.appendChild(element("div", "subtitle", report.subtitle));
    var stats = element("div", "stats");
    (report.stats || []).forEach(function (item) {
      var stat = element("div", "stat");
      stat.appendChild(element("span", "", item[0]));
      stat.appendChild(element("b", "", item[1]));
      stats.appendChild(stat);
    });
    header.appendChild(stats);
    root.appendChild(header);

    var toc = element("nav", "toc");
    toc.setAttribute("aria-label", "报告目录");
    (report.sections || []).forEach(function (section, index) {
      var link = element("a", "", section.title);
      link.href = "#section-" + (index + 1);
      toc.appendChild(link);
    });
    root.appendChild(toc);

    (report.sections || []).forEach(function (section, index) {
      var sectionNode = element("section");
      sectionNode.id = "section-" + (index + 1);
      sectionNode.appendChild(element("h2", "", section.title));
      (section.notes || []).forEach(function (note, noteIndex) {
        if (typeof note === "string") {
          sectionNode.appendChild(element("div", "note", note));
          return;
        }
        var aside = element("aside", "note " + (note.tone || "info"));
        aside.appendChild(element("strong", "", note.title || (noteIndex ? "说明" : "本周结论")));
        aside.appendChild(document.createTextNode(note.text || ""));
        sectionNode.appendChild(aside);
      });
      (section.tables || []).forEach(function (table) {
        sectionNode.appendChild(renderTable(table));
      });
      root.appendChild(sectionNode);
    });
  }

  fetch("./data.json", { cache: "no-store" })
    .then(function (response) {
      if (!response.ok) throw new Error("HTTP " + response.status);
      return response.json();
    })
    .then(render)
    .catch(function (error) {
      var root = document.getElementById("report-root");
      root.textContent = "";
      root.appendChild(element("p", "load-error", "报告数据加载失败：" + error.message));
    });
}());
