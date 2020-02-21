$(document).ready(async () => {

// load and compile stylesheet
(await Promise.all([
    window.location.pathname + "static/style.less",
    window.location.pathname + "static/tooltip.less"
].map(async (path) => {
    let styleless = await (await fetch(path)).text();
    let stylecss = await less.render(styleless, {
        rootpath: path.substr(0, path.lastIndexOf("/"))
    });
    return stylecss;
}))).forEach((stylecss) => {
    $('<style type="text/css">' + stylecss.css + '</style>').appendTo("head");
});

// wait for preload images
await (() => {
    let promises = [];
    $(".image-preloads img").each((i, el) => {
        promises.push(new Promise((resolve, reject) => {
            el.onload = resolve;
            el.onerror = reject;
            if (el.complete) {
                el.onload = null;
                el.onerror = null;
                resolve();
            }
        }));
    });
    return Promise.all(promises);
})();

// show page
$(".page-load").remove();

// prepare some DOM objects
let $ImageItemTplEl = $("#image-item-template");
let imageItemSize = {
    width: parseInt($ImageItemTplEl.width()),
    height: parseInt($ImageItemTplEl.height())
};
let $ImageListBottomEl = $("#image-list-bottom");
let $ImageListBottomLoadingSloganEl = $ImageListBottomEl.find("#slogan-loading");
(() => {
    let ndots = 1;
    setInterval(() => {
        $ImageListBottomLoadingSloganEl.text("Loading" + _.padStart("", ndots, "."));
        ndots += 1;
        if (ndots == 7) ndots = 1;
    }, 500);
})();
let $ImageViewerBGEl = $("#image-viewer-background");
let $ImageViewerWrapperEl = $("#image-viewer-wrapper");
let $ImageViewerEl = $("#image-viewer");
let $ImageViewerImageEl = $("#image-viewer-image");
let $ImageViewerPreloadEl = $("#image-viewer-preload");
let $FilterStartButton = $("#button-filter");
let $FilterCloseButton = $("#button-filter-close");
let $FilterSelectYear = $("#filter-select-year");
let $FilterSelectMonth = $("#filter-select-month");

// load config file
const config = await (await fetch(window.location.pathname + "static/config.json")).json();

// create OSS client
window.oss = new OSS(config.oss);

// image list request methods
const pagesize = 15;
let marker = undefined;
let loading = false;
let completed = false;
let prefix = "image/"
const setLoading = (value) => {
    loading = value;
    if (loading) {
        $ImageListBottomEl.addClass("loading");
        $ImageListBottomEl.removeClass("complete");
        $ImageListBottomEl.removeClass("empty");
    }
    else {
        $ImageListBottomEl.removeClass("loading");
        if ($("#image-list .image-item").length == 0) $ImageListBottomEl.addClass("empty");
        else $ImageListBottomEl.removeClass("empty");
    }
};
const setComplete = (value) => {
    completed = value;
    if (completed) $ImageListBottomEl.addClass("complete");
    else $ImageListBottomEl.removeClass("complete");
    if ($("#image-list .image-item").length == 0) $ImageListBottomEl.addClass("empty");
    else $ImageListBottomEl.removeClass("empty");
};
const readList = async (options) => {
    options = options || {};
    if (!options.first && marker === undefined) {
        setComplete(true);
        return [];
    }
    if (loading) return [];
    setLoading(true);
    let result = {};
    try {
        result = await oss.list({
            "prefix": prefix,
            "max-keys": pagesize,
            "marker": marker
        });
    } catch (e) {
        setLoading(false);
        return [];
    }
    if (result.isTruncated) {
        marker = result.nextMarker;
        setComplete(false);
    }
    else {
        marker = undefined;
        setComplete(true);
    }
    if (result.objects) {
        result.objects.forEach((item) => {
            let name = item.name;
            let match = /^image\/(\d{8})\-([a-zA-Z0-9]+)\.(\w+)$/.exec(name);
            let startdate = _.padStart("" + (99999999 - parseInt(match[1])), 8, "0");
            let hshid = match[2];
            let suffix = match[3];
            let el =
            $ImageItemTplEl
                .clone()
                .attr("id", "image-" + hshid)
                .data("file", item)
                .appendTo("#image-list");
            el.find(".image-item-image")
            .one("load", function() {
                $(this).closest(".image-item").addClass("done");
            })
            .attr("src", "http://" + config.oss.bucket + "." + config.oss.region + ".aliyuncs.com/" + name + "?x-oss-process=image/resize,m_fill,h_" + imageItemSize.height + ",w_" + imageItemSize.width);
        });
    }
    setLoading(false);
    return result.objects || [];
};

// load the first page of images
const reloadList = async () => {
    $("#image-list").children().remove();
    await readList({ first: true });
    while ($(window).height() >= $(document).height() && !completed) {
        await readList();
    }
};
await reloadList();

// handle scroll events
$(window).on("mousewheel", (event) => {
    if (event.deltaY < 0 && $(window).height() + $(window).scrollTop() == $(document).height()) readList();
});

// view image
let currViewEl = undefined;
$(".image-viewer-wrapper").on("click", function(event) {
    event.stopPropagation();
});
$(".image-viewer-background").on("click", function(event) {
    $(this).hide();
});
const resizeImageViewer = () => {
    let width = $ImageViewerPreloadEl.width();
    let height = $ImageViewerPreloadEl.height();
    if (width == 0 || height == 0) return;
    let wrapperWidth = $ImageViewerWrapperEl.width();
    let wrapperHeight = $ImageViewerWrapperEl.height();
    if (wrapperWidth == 0 || wrapperHeight == 0) return;
    let sc = Math.min(wrapperWidth / width, wrapperHeight / height) * 0.9;
    let newWidth = width * sc;
    let newHeight = height * sc;
    $ImageViewerEl.css({
        width: newWidth,
        height: newHeight,
        left: (wrapperWidth - newWidth) / 2,
        top: (wrapperHeight - newHeight) / 2
    });
};
const viewImage = (imageItemEl) => {
    let fileitem = $(imageItemEl).data("file");
    if (!fileitem) return;
    currViewEl = $(imageItemEl);
    let fileurl = "http://" + config.oss.bucket + "." + config.oss.region + ".aliyuncs.com/" + fileitem.name;
    $ImageViewerImageEl.hide();
    $ImageViewerBGEl.show();
    $ImageViewerPreloadEl
        .off("load")
        .one("load", () => {
            resizeImageViewer();
            $ImageViewerImageEl.attr("src", fileurl).show();
        })
        .attr("src", fileurl);
};
const closeViewImage = () => {
    $ImageViewerBGEl.hide();
};
$(document).on("click", ".image-item", function() {
    viewImage(this);
});
$(window).on("resize", closeViewImage);
$("#image-viewer-prev").click(() => {
    if (currViewEl) {
        let gotoEl = currViewEl.prev();
        if (gotoEl.length > 0) viewImage(gotoEl);
    }
});
$("#image-viewer-next").click(() => {
    if (currViewEl) {
        let gotoEl = currViewEl.next();
        if (gotoEl.length > 0) viewImage(gotoEl);
    }
});
$("#image-viewer-close").click(closeViewImage);

// filter bar
$FilterStartButton.click(() => {
    $("#filter-bar-inactive").hide();
    $("#filter-bar-active").show();
});
$FilterCloseButton.click(() => {
    $("#filter-bar-inactive").show();
    $("#filter-bar-active").hide();
    let newprefix = "image/";
    if (newprefix != prefix) {
        prefix = newprefix;
        reloadList();
    }

});
$(".select > .button-text").on("click", function(event) {
    event.stopPropagation();
    let selectEl = $(this).parent();
    let isActive = selectEl.is(".active");
    $(".select").removeClass("active");
    if (selectEl.is("[disabled]")) return;
    if (!isActive) {
        selectEl.addClass("active");
        selectEl.trigger("open");
    }
});
$(".select,.button").on("contextmenu", function(event) {
    event.preventDefault();
    event.stopPropagation();
});
$(".select").on("click", ".select-options", function(event) {
    event.stopPropagation();
});
$(document).on("click", function() {
    $(".select").removeClass("active");
});
const original_jq_fn_clear = $.fn.clear;
$.fn.clear = function() {
    if ($(this).is(".select")) {
        let selectEl = $(this);
        let oldValue = selectEl.data("value") || "";
        selectEl.data("value", null);
        selectEl.children(".button-text").text(selectEl.attr("empty-value") || "");
        selectEl.trigger("change", [{
            oldValue: oldValue,
            value: ""
        }]);
        return;
    }
    if (original_jq_fn_clear)
        return original_jq_fn_clear.apply(this, arguments);
};
const original_jq_fn_value = $.fn.value;
$.fn.value = function(setValue) {
    if ($(this).is(".select")) {
        let selectEl = $(this);
        if (setValue === undefined) {
            return selectEl.data("value") || "";
        } else {
            let oldValue = selectEl.data("value") || "";
            let newValue = setValue;
            if (oldValue == newValue) return;
            selectEl.data("value", newValue);
            selectEl.children(".button-text").text(newValue || selectEl.attr("empty-value") || "");
            selectEl.trigger("change", [{
                oldValue: oldValue,
                value: newValue
            }]);
        }
    }
    if (original_jq_fn_value)
        return original_jq_fn_value.apply(this, arguments);
};
$(".select").each(function() {
    $(this).clear();
});
$(".select").on("click", ".button-option", function (event) {
    let selectEl = $(this).closest(".select");
    if (selectEl.is("[disabled]")) return;
    selectEl.value($(this).text());
    selectEl.removeClass("active");
});
$(".select > .button-text").on("contextmenu", function(event) {
    let selectEl = $(this).closest(".select");
    if (selectEl.is("[disabled]")) return;
    selectEl.closest(".select").clear();
});
const updateYearSelectOptions = (year) => {
    if (year == undefined) year = new Date().getFullYear();
    year = parseInt(year);
    let year0 = parseInt(year / 10) * 10;
    let optionEls = $("#filter-select-year").find(".button-option");
    for (let i = 0; i < 10; i++)
        $(optionEls[i]).text("" + (year0 + i));
};
$("#filter-select-year").on("open", () => {
    let curvalue = $("#filter-select-year").value();
    if (curvalue) updateYearSelectOptions(curvalue);
    else updateYearSelectOptions();
});
$("#filter-select-year").on("change", (event, data) => {
    if (!data.value) {
        $("#filter-select-month").clear();
        $("#filter-select-month").attr("disabled", true);
    } else {
        $("#filter-select-month").removeAttr("disabled");
    }
});
$("#button-filter-year-prev").on("click", () => {
    let curyear0 = parseInt($($("#filter-select-year").find(".button-option")[0]).text());
    updateYearSelectOptions(curyear0 - 10);
});
$("#button-filter-year-next").on("click", () => {
    let curyear0 = parseInt($($("#filter-select-year").find(".button-option")[0]).text());
    updateYearSelectOptions(curyear0 + 10);
});
$("#filter-select-month").attr("disabled", true);
$("#filter-select-year").on("change", function (event, data) {
    if (data.value)
        $(this).attr("tooltip", "Right-click to CLEAR");
    else
        $(this).attr("tooltip", "Year filter");
});
$("#filter-select-month").on("change", function (event, data) {
    if (data.value)
        $(this).attr("tooltip", "Right-click to CLEAR");
    else
        $(this).attr("tooltip", "Month filter");
});

// Year-Month filter logics
const monthStrList = (() => {
    let optionEls = $("#filter-select-month .button-option");
    let optionStrs = [];
    for (let i = 0; i < optionEls.length; i++) {
        optionStrs.push($(optionEls[i]).text());
    }
    return optionStrs;
})();
const onYearMonthFilterChanged = () => {
    if (onYearMonthFilterChanged.disabled) return;
    let newyear = $("#filter-select-year").value() || undefined;
    let newmonth = $("#filter-select-month").value() || undefined;
    let newprefix = "image/";
    if (newyear) {
        newyear = _.padStart("" + (9999 - parseInt(newyear)), 4, "0");
        newprefix += newyear;
        if (newmonth) {
            newmonth = _.padStart("" + (11 - monthStrList.indexOf(newmonth)), 2, "0");
            newprefix += newmonth;
        }
    }
    if (newprefix != prefix) {
        prefix = newprefix;
        reloadList();
    }
};
onYearMonthFilterChanged.disabled = false;
$("#filter-select-year,#filter-select-month").on("change", onYearMonthFilterChanged);
const filterNavigate = (amount) => {
    if (amount == 0) return;
    let year = $("#filter-select-year").value() || undefined;
    let month = $("#filter-select-month").value() || undefined;
    if (!year) return;
    year = parseInt(year);
    if (month) {
        month = monthStrList.indexOf(month);
        if (amount > 0) {
            if (month < 11) {
                month += 1;
            } else {
                month = 0;
                year += 1;
            }
        } else {
            if (month > 0) {
                month -= 1;
            } else {
                month = 11;
                year -= 1;
            }
        }
        month = monthStrList[month];
    } else {
        if (amount > 0) year += 1;
        else year -= 1;
    }
    year = "" + year;
    onYearMonthFilterChanged.disabled = true;
    if (year) $("#filter-select-year").value(year);
    if (month) $("#filter-select-month").value(month);
    onYearMonthFilterChanged.disabled = false;
    onYearMonthFilterChanged();
};
$("#button-filter-next").on("click", () => {
    filterNavigate(1);
});
$("#button-filter-prev").on("click", () => {
    filterNavigate(-1);
});

});