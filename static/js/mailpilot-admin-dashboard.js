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
    return chart;
  }

  function hexToRgba(hex, alpha) {
    var h = (hex || "").replace("#", "");
    if (h.length === 3) {
      h = h.split("").map(function (c) { return c + c; }).join("");
    }
    if (h.length !== 6) return "rgba(79,110,247," + alpha + ")";
    var r = parseInt(h.slice(0, 2), 16);
    var g = parseInt(h.slice(2, 4), 16);
    var b = parseInt(h.slice(4, 6), 16);
    return "rgba(" + r + "," + g + "," + b + "," + alpha + ")";
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

  (function () {
    var standardPlanColors = {
      starter: "#3b82f6",
      pro: "#10b981",
      custom: "#8b5cf6",
    };
    var fallbackPlanColors = ["#3b82f6", "#10b981", "#8b5cf6", "#f59e0b"];
    var sliceColors = (data.plan_mix.labels || []).map(function (label, idx) {
      var key = String(label || "").toLowerCase().trim();
      return standardPlanColors[key] || fallbackPlanColors[idx % fallbackPlanColors.length];
    });
    if (!sliceColors.length) {
      sliceColors = data.plan_mix.colors || fallbackPlanColors;
    }
    var sliceStroke = document.documentElement.classList.contains("dark") ? "#1e293b" : "#ffffff";
    var isDark = document.documentElement.classList.contains("dark");
    var donutHole = isDark ? "#0f172a" : "#ffffff";

    mount("mpChartPlanMix", {
      chart: {
        type: "donut",
        height: 300,
        fontFamily: font,
        toolbar: { show: false },
        dropShadow: { enabled: false },
        animations: {
          enabled: true,
          easing: "easeinout",
          speed: 400,
        },
      },
      series: data.plan_mix.series,
      labels: data.plan_mix.labels,
      colors: sliceColors,
      fill: { type: "solid", opacity: 1 },
      legend: {
        position: "bottom",
        labels: { colors: "#94a3b8" },
        markers: { width: 10, height: 10, radius: 10 },
      },
      dataLabels: {
        enabled: true,
        dropShadow: { enabled: false },
        style: { fontSize: "12px", fontWeight: 700, colors: ["#ffffff"] },
      },
      states: {
        hover: { filter: { type: "none" } },
        active: { filter: { type: "none" } },
      },
      plotOptions: {
        pie: {
          expandOnClick: false,
          customScale: 1,
          donut: {
            size: "68%",
            background: donutHole,
            labels: {
              show: true,
              name: {
                show: true,
                fontSize: "13px",
                fontWeight: 600,
                color: "#94a3b8",
                offsetY: -4,
              },
              value: {
                show: true,
                fontSize: "22px",
                fontWeight: 700,
                color: isDark ? "#e2e8f0" : "#1e293b",
                offsetY: 4,
              },
              total: {
                show: true,
                label: "Users",
                fontSize: "13px",
                fontWeight: 600,
                color: "#94a3b8",
                formatter: function (w) {
                  return w.globals.seriesTotals.reduce(function (a, b) { return a + b; }, 0);
                },
              },
            },
          },
        },
      },
      stroke: { show: true, width: 2, colors: [sliceStroke] },
      tooltip: {
        theme: tooltipTheme,
        custom: function (ctx) {
          var idx = ctx.seriesIndex;
          var names = (data.plan_mix.user_names && data.plan_mix.user_names[idx]) || [];
          var label = data.plan_mix.labels[idx] || "";
          var count = ctx.series[ctx.seriesIndex];
          var accent = sliceColors[idx] || "#4f6ef7";
          var list = names.length
            ? names.map(function (n) { return "<li>" + n + "</li>"; }).join("")
            : "<li>No users</li>";
          return (
            '<div class="mp-dash-donut-tooltip">' +
            '<div class="mp-dash-donut-tooltip__head" style="--mp-tip-a:' + accent + ";--mp-tip-b:" + accent + '">' +
            label + " · " + count + " user" + (count === 1 ? "" : "s") +
            "</div>" +
            '<ul class="mp-dash-donut-tooltip__body">' + list + "</ul></div>"
          );
        },
      },
    });
  })();

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
