function toggleCheckboxes(value) {
	myform = document.getElementById("frmResults");
	checkboxes = myform.getElementsByTagName("input");
	for (index = 0, len = checkboxes.length; index < len; ++index) {
		if(checkboxes[index].type=='checkbox')
			checkboxes[index].checked = value;
	}
}

function loadCities(url) {
	clearCities();
	$.getJSON(url, function(obj) {
			$.each(obj,function(key,value)
			{
			$("#" + ajax_city_prefix + "city").append("<option value='" + key + "'>" + value + "</option>");
			});
	});
}
function clearCities() {
	$("#" + ajax_city_prefix + "city").empty();
}
function loadCitiesByCountry() {
	country = $("#" + ajax_city_prefix + "country").val();
	$("#" + ajax_city_prefix + "region").val('');
	if (country != "") {
		path = "/editor/cities/list/?country=" + country;
		if (typeof ajax_cur_city != 'undefined')
			path += "&cur_city=" + ajax_cur_city;
		loadCities(path);
	} else {
		clearCities();
	}
}
function loadCitiesByRegion() {
	region = $("#" + ajax_city_prefix + "region").val();
	$("#" + ajax_city_prefix + "country").val('');
	if (region != "") {
		path = "/editor/cities/list/?region=" + region;
		if (typeof ajax_cur_city != 'undefined')
			path += "&cur_city=" + ajax_cur_city;
		loadCities(path);
	} else {
		clearCities();
	}
}

$(document).ready(function() {
	if (typeof ajax_city_prefix != 'undefined') {
		clearCities();
		$("#" + ajax_city_prefix + "city").append("<option value=''>Укажите страну или регион</option>");

		$("#" + ajax_city_prefix + "country").change(loadCitiesByCountry);
		$("#" + ajax_city_prefix + "region").change(loadCitiesByRegion);
		if ($("#" + ajax_city_prefix + "country").val() != "") {
			loadCitiesByCountry();
		} else if ($("#" + ajax_city_prefix + "region").val() != "") {
			loadCitiesByRegion();
		}
	}

	$('input#id_is_new_city').change(function () {
			if ($('input#id_is_new_city').is(':checked')) {
					$('div#div-new-city').removeClass('collapse');
			} else {
					$('div#div-new-city').addClass('collapse');
			}
	});

});

function claim_result(link, name, race_name, race_distance, result) {
	var retVal = confirm("Результат " + result + " на забеге «"
    + race_name + "» на дистанцию " + race_distance + " под именем «" + name
    + "» – действительно ваш? Если да, но при этом имя отличается от каждого из ваших, "
    + "рекомендуем оставить комментарий администраторам.");
	if (retVal != null)
    window.location = link + "?comment=" + encodeURIComponent(retVal);
}
