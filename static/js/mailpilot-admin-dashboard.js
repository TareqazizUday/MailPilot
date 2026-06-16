(function () {
  "use strict";

  var el = document.getElementById("mp-dashboard-charts");
  if (!el || typeof ApexCharts === "undefined") return;

  var data;
  try {
    data = JSON.parse(el.textContent);
  } catch (e) {
    return;
  }

  var font = "Inter, system-ui, sans-serif";
  var grid = { borderColor: "rgba(148,163,184,0.12)", strokeDashArray: 4 };
  var axis = {
    labels: { style: { colors: "#94a3b8", fontSize: "11px", fontFamily: font } },
    axisBorder: { show: false },
    axisTicks: { show: false },
  };
  var tooltipTheme = document.documentElement.classList.contains("dark") ? "dark" : "light";

  function mount(id, options) {
    var node = document.getElementById(id);
    if (!node) return;
    var chart = new ApexCharts(node, options);
    chart.render();
  }

  function horizHeight(labelCount) {
    return Math.max(220, Math.min(420, labelCount * 36 + 48));
  }

  function horizCategoryAxis(labels) {
    return {
      xaxis: {
        categories: labels,
        labels: {
          style: { colors: "#94a3b8", fontSize: "11px", fontFamily: font },
        },
      },
      yaxis: {
        labels: {
          style: { colors: "#94a3b8", fontSize: "11px", fontFamily: font },
          formatter: function (v) {
            return Number.isFinite(v) ? Math.round(v) : v;
          },
        },
        axisBorder: { show: false },
        axisTicks: { show: false },
        decimalsInFloat: 0,
        forceNiceScale: true,
      },
    };
  }

  mount("mpChartPlanMix", {
    chart: { type: "donut", height: 300, fontFamily: font, toolbar: { show: false } },
    series: data.plan_mix.series,
    labels: data.plan_mix.labels,
    colors: data.plan_mix.colors,
    legend: { position: "bottom", labels: { colors: "#94a3b8" } },
    dataLabels: { enabled: true, style: { fontSize: "12px", fontWeight: 600 } },
    plotOptions: {
      pie: {
        donut: {
          size: "68%",
          labels: {
            show: true,
            total: {
              show: true,
              label: "Users",
              color: "#94a3b8",
              formatter: function (w) {
                return w.globals.seriesTotals.reduce(function (a, b) { return a + b; }, 0);
              },
            },
          },
        },
      },
    },
    stroke: { width: 0 },
    tooltip: {
      theme: tooltipTheme,
      custom: function (ctx) {
        var idx = ctx.seriesIndex;
        var names = (data.plan_mix.user_names && data.plan_mix.user_names[idx]) || [];
        var label = data.plan_mix.labels[idx] || "";
        var count = ctx.series[ctx.seriesIndex];
        var list = names.length
          ? names.map(function (n) { return "<li>" + n + "</li>"; }).join("")
          : "<li>No users</li>";
        return (
          '<div class="apexcharts-tooltip-title" style="padding:8px 10px;font-weight:600;">' +
          label + " (" + count + ")</div>" +
          '<ul style="margin:0;padding:8px 12px 10px 22px;font-size:12px;line-height:1.5;">' +
          list + "</ul>"
        );
      },
    },
  });

  if (data.users_by_plan && data.users_by_plan.labels && data.users_by_plan.labels.length) {
    mount("mpChartUsersByPlan", Object.assign({
      chart: { type: "bar", height: horizHeight(data.users_by_plan.labels.length), fontFamily: font, toolbar: { show: false } },
      series: [{ name: "Tokens used", data: data.users_by_plan.series }],
      colors: data.users_by_plan.colors,
      plotOptions: { bar: { horizontal: true, borderRadius: 6, barHeight: "62%", distributed: true } },
      dataLabels: {
        enabled: true,
        formatter: function (val, opts) {
          var plan = data.users_by_plan.plans[opts.dataPointIndex] || "";
          return plan + (val ? " · " + val : "");
        },
        style: { fontSize: "10px", fontWeight: 600, colors: ["#fff"] },
      },
      grid: grid,
      legend: { show: false },
      tooltip: {
        theme: tooltipTheme,
        y: {
          formatter: function (val, opts) {
            var plan = data.users_by_plan.plans[opts.dataPointIndex] || "";
            return plan + " — " + val + " tokens";
          },
        },
      },
    }, horizCategoryAxis(data.users_by_plan.labels)));
  }

  if (data.top_token_chart && data.top_token_chart.labels && data.top_token_chart.labels.length) {
    mount("mpChartTopUsers", Object.assign({
      chart: { type: "bar", height: horizHeight(data.top_token_chart.labels.length), fontFamily: font, toolbar: { show: false } },
      series: [{ name: "Tokens used", data: data.top_token_chart.series }],
      colors: ["#4f6ef7"],
      plotOptions: { bar: { horizontal: true, borderRadius: 6, barHeight: "62%" } },
      dataLabels: { enabled: true, style: { fontSize: "11px", fontWeight: 600 } },
      grid: grid,
      tooltip: { theme: tooltipTheme },
    }, horizCategoryAxis(data.top_token_chart.labels)));
  }

  mount("mpChartTokens", {
    chart: { type: "area", height: 280, fontFamily: font, toolbar: { show: false }, sparkline: { enabled: false } },
    series: [{ name: "Tokens", data: data.tokens_monthly.series }],
    colors: ["#4f6ef7"],
    xaxis: Object.assign({}, axis, { categories: data.tokens_monthly.labels }),
    yaxis: Object.assign({}, axis, { labels: Object.assign({}, axis.labels, { formatter: function (v) { return Math.round(v); } }) }),
    grid: grid,
    fill: {
      type: "gradient",
      gradient: { shadeIntensity: 1, opacityFrom: 0.45, opacityTo: 0.05, stops: [0, 90, 100] },
    },
    stroke: { curve: "smooth", width: 3 },
    dataLabels: { enabled: false },
    tooltip: { theme: tooltipTheme },
  });

  mount("mpChartSignups", {
    chart: { type: "line", height: 280, fontFamily: font, toolbar: { show: false } },
    series: [{ name: "Signups", data: data.signups_monthly.series }],
    colors: ["#a78bfa"],
    xaxis: Object.assign({}, axis, { categories: data.signups_monthly.labels }),
    yaxis: axis,
    grid: grid,
    stroke: { curve: "smooth", width: 3 },
    markers: { size: 4, strokeWidth: 0 },
    dataLabels: { enabled: false },
    tooltip: { theme: tooltipTheme },
  });

  if (data.mailboxes_by_user && data.mailboxes_by_user.labels && data.mailboxes_by_user.labels.length) {
    var mbLabels = data.mailboxes_by_user.labels;
    var mbGmail = data.mailboxes_by_user.gmail;
    var mbSmtp = data.mailboxes_by_user.smtp;
    mount("mpChartMailboxesByUser", Object.assign({
      chart: {
        type: "bar",
        height: horizHeight(mbLabels.length),
        fontFamily: font,
        toolbar: { show: false },
        stacked: false,
      },
      series: [
        { name: "Gmail", data: mbGmail },
        { name: "SMTP/IMAP", data: mbSmtp },
      ],
      colors: ["#4f6ef7", "#38bdf8"],
      plotOptions: { bar: { horizontal: true, borderRadius: 4, barHeight: "70%" } },
      grid: grid,
      legend: { position: "top", labels: { colors: "#94a3b8" } },
      dataLabels: { enabled: false },
      tooltip: {
        theme: tooltipTheme,
        shared: true,
        intersect: false,
        custom: function (ctx) {
          var i = ctx.dataPointIndex;
          var name = mbLabels[i] || "";
          var g = mbGmail[i] || 0;
          var s = mbSmtp[i] || 0;
          return (
            '<div style="padding:8px 10px;font-size:12px;line-height:1.5">' +
            "<strong>" + name + "</strong><br>" +
            "Gmail: " + g + "<br>SMTP/IMAP: " + s +
            "</div>"
          );
        },
      },
    }, horizCategoryAxis(mbLabels)));
  } else {
    mount("mpChartTransport", {
      chart: { type: "bar", height: 280, fontFamily: font, toolbar: { show: false } },
      series: [{ name: "Mailboxes", data: data.mail_transport.series }],
      colors: data.mail_transport.colors,
      plotOptions: { bar: { borderRadius: 8, columnWidth: "42%", distributed: true } },
      xaxis: Object.assign({}, axis, { categories: data.mail_transport.labels }),
      yaxis: axis,
      grid: grid,
      legend: { show: false },
      dataLabels: { enabled: true, style: { fontSize: "12px", fontWeight: 600 } },
      tooltip: { theme: tooltipTheme },
    });
  }

  if (data.integration_users && data.integration_users.labels && data.integration_users.labels.length) {
    mount("mpChartIntegrations", Object.assign({
      chart: {
        type: "bar",
        height: horizHeight(data.integration_users.labels.length),
        fontFamily: font,
        toolbar: { show: false },
        stacked: false,
      },
      series: [
        { name: "Telegram", data: data.integration_users.telegram },
        { name: "WhatsApp", data: data.integration_users.whatsapp },
      ],
      colors: ["#4f6ef7", "#10b981"],
      plotOptions: { bar: { horizontal: true, borderRadius: 4, barHeight: "70%" } },
      grid: grid,
      legend: { position: "top", labels: { colors: "#94a3b8" } },
      dataLabels: { enabled: false },
      tooltip: { theme: tooltipTheme, shared: true, intersect: false },
    }, horizCategoryAxis(data.integration_users.labels), {
      yaxis: {
        labels: {
          style: { colors: "#94a3b8", fontSize: "11px", fontFamily: font },
          formatter: function (v) {
            return Number.isFinite(v) ? Math.round(v) : v;
          },
        },
        axisBorder: { show: false },
        axisTicks: { show: false },
        decimalsInFloat: 0,
        max: 1,
        tickAmount: 2,
      },
    }));
  } else {
    mount("mpChartIntegrations", {
      chart: { type: "bar", height: 280, fontFamily: font, toolbar: { show: false } },
      series: [
        { name: "Plan enabled", data: data.integrations.entitled },
        { name: "Configured", data: data.integrations.configured },
      ],
      colors: ["#4f6ef7", "#10b981"],
      plotOptions: { bar: { borderRadius: 6, columnWidth: "55%" } },
      xaxis: Object.assign({}, axis, { categories: data.integrations.labels }),
      yaxis: axis,
      grid: grid,
      legend: { position: "top", labels: { colors: "#94a3b8" } },
      dataLabels: { enabled: false },
      tooltip: { theme: tooltipTheme },
    });
  }

  mount("mpChartAutoSends", {
    chart: { type: "area", height: 280, fontFamily: font, toolbar: { show: false } },
    series: [{ name: "Auto-sends", data: data.auto_sends_daily.series }],
    colors: ["#10b981"],
    xaxis: Object.assign({}, axis, {
      categories: data.auto_sends_daily.labels,
      labels: Object.assign({}, axis.labels, { rotate: -45, hideOverlappingLabels: true }),
    }),
    yaxis: axis,
    grid: grid,
    stroke: { curve: "smooth", width: 2 },
    fill: {
      type: "gradient",
      gradient: { shadeIntensity: 1, opacityFrom: 0.35, opacityTo: 0.02 },
    },
    dataLabels: { enabled: false },
    tooltip: { theme: tooltipTheme },
  });

  mount("mpChartPaid", {
    chart: { type: "bar", height: 280, fontFamily: font, toolbar: { show: false } },
    series: [{ name: "New paid", data: data.paid_conversions.series }],
    colors: ["#f59e0b"],
    plotOptions: { bar: { borderRadius: 8, columnWidth: "50%" } },
    xaxis: Object.assign({}, axis, { categories: data.paid_conversions.labels }),
    yaxis: axis,
    grid: grid,
    dataLabels: { enabled: true, style: { fontSize: "11px" } },
    tooltip: { theme: tooltipTheme },
  });

  var tbody = document.getElementById("mpTopTokenBody");
  if (tbody && data.top_token_users && data.top_token_users.length) {
    data.top_token_users.forEach(function (row) {
      var tr = document.createElement("tr");
      var pct = row.pct != null ? row.pct : null;
      var barTone = pct == null ? "custom" : pct >= 95 ? "danger" : pct >= 70 ? "warn" : "ok";
      var barWidth = pct != null ? pct : 100;
      var usageCell =
        pct != null
          ? '<span class="mp-usage"><span class="mp-usage-bar mp-usage-' +
            barTone +
            '"><i style="width:' +
            barWidth +
            '%"></i></span><span class="mp-usage-label">' +
            row.used +
            " / " +
            row.limit +
            "</span></span>"
          : '<span class="mp-badge mp-badge-custom">' + row.used + " tokens</span>";
      var nameCell =
        '<div class="mp-dash-user-name">' + row.name + "</div>" +
        (row.email && row.email !== row.name
          ? '<div class="mp-dash-user-email">' + row.email + "</div>"
          : "");
      tr.innerHTML =
        "<td>" + nameCell + "</td><td>" + row.plan + "</td><td>" + usageCell + "</td>";
      tbody.appendChild(tr);
    });
  } else if (tbody) {
    tbody.innerHTML =
      '<tr><td colspan="3" class="mp-dash-empty">No token usage this period yet.</td></tr>';
  }
})();
