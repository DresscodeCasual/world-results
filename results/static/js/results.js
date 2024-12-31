function loadCities(url, is_initial) {
	clearCities();
	var arrOptions = [];
	arrOptions[0] = "<option value=''>не указан</option>";
	var i = 1;
	if (typeof ajax_city_fullname != 'undefined')
		url += "&full=1";
	$.getJSON(url, function(obj) {
		$.each(obj.cities, function(i, city) {
			arrOptions[i+1] = ("<option value='" + city.key + "'>" + city.value + "</option>");
		});
		$("#" + ajax_city_prefix + "city_id").append(arrOptions.join(''));
		if (is_initial == 1) {
			if (typeof ajax_city_default != 'undefined')
				$("#" + ajax_city_prefix + "city_id").val(ajax_city_default);
		}
	});
}
function clearCities() {
	$("#" + ajax_city_prefix + "city_id").empty();
}
function loadCitiesByCountry(is_initial) {
	if (is_initial === undefined) is_initial = 0;
	country = $("#" + ajax_city_prefix + "country").val();
	$("#" + ajax_city_prefix + "region").val('');
	if (country != "") {
		path = "/editor/cities/list/?country=" + country;
		if (typeof ajax_cur_city != 'undefined')
			path += "&cur_city=" + ajax_cur_city;
		loadCities(path, is_initial);
	} else {
		clearCities();
		$("#" + ajax_city_prefix + "city_id").append("<option value=''>выберите страну или регион</option>");
	}
}
function loadCitiesByRegion(is_initial) {
	if (is_initial === undefined) is_initial = 0;
	region = $("#" + ajax_city_prefix + "region").val();
	$("#" + ajax_city_prefix + "country").val('');
	if (region != "") {
		path = "/editor/cities/list/?region=" + region;
		if (typeof ajax_cur_city != 'undefined')
			path += "&cur_city=" + ajax_cur_city;
		loadCities(path, is_initial);
	} else {
		clearCities();
		$("#" + ajax_city_prefix + "city_id").append("<option value=''>выберите страну или регион</option>");
	}
}

function initCities() {
	if (typeof ajax_city_prefix != 'undefined') {
		clearCities();
		$("#" + ajax_city_prefix + "city_id").append("<option value=''>выберите страну или регион</option>");

		$("#" + ajax_city_prefix + "country").change(loadCitiesByCountry);
		$("#" + ajax_city_prefix + "region").change(loadCitiesByRegion);
		if ($("#" + ajax_city_prefix + "region").val() != "") {
			loadCitiesByRegion(1);
		} else if ($("#" + ajax_city_prefix + "country").val() != "") {
			loadCitiesByCountry(1);
		}
	}
}

var lastChecked = null;
var lastChecked_gender = null;
var lastChecked_category = null;

$(document).ready(function() {
	initCities();
	$('input#id_is_new_city').change(function () {
			if ($('input#id_is_new_city').is(':checked')) {
					$('#div-new-city').removeClass('collapse');
			} else {
					$('#div-new-city').addClass('collapse');
			}
	});
	$('#table_for_sort').DataTable( {
		"paging": false,
		"bInfo": false,
		"columnDefs": [ {
			"orderable" : false,
			"targets" : [ "no-sort" ]
		} ],
		"language": {
			"search": "Поиск по всем столбцам"
				}
	});
	var $chkboxes = $('.chkbox');
	$chkboxes.click(function(e) {
		if(!lastChecked) {
			lastChecked = this;
			return;
		}
		if(e.shiftKey) {
			var start = $chkboxes.index(this);
			var end = $chkboxes.index(lastChecked);
			$chkboxes.slice(Math.min(start,end), Math.max(start,end) + 1).prop('checked', lastChecked.checked);
		}
		lastChecked = this;
	});
	var $chkboxes_gender = $('.chkbox_gender');
	$chkboxes_gender.click(function(e) {
		if(!lastChecked_gender) {
			lastChecked_gender = this;
			return;
		}
		if(e.shiftKey) {
			var start = $chkboxes_gender.index(this);
			var end = $chkboxes_gender.index(lastChecked_gender);
			$chkboxes_gender.slice(Math.min(start,end), Math.max(start,end) + 1).prop('checked', lastChecked_gender.checked);
		}
		lastChecked_gender = this;
	});
	var $inputs_category = $('.category_row');
	$inputs_category.click(function(e) {
		if(!lastChecked_category) {
			lastChecked_category = this;
			return;
		}
		if(e.shiftKey) {
			var start = $inputs_category.index(this);
			var end = $inputs_category.index(lastChecked_category);
			$inputs_category.slice(Math.min(start,end), Math.max(start,end) + 1).val(lastChecked_category.value);
		}
		lastChecked_category = this;
	});
	$('.toggle_chkbox').click(function() {
		var checkedStatus = this.checked;
		$chkboxes.prop('checked', checkedStatus);
	});
	$('.toggle_chkbox_gender').click(function() {
		var checkedStatus = this.checked;
		$chkboxes_gender.prop('checked', checkedStatus);
	});
	$("a#send_to_info_page").click(function(){
		var url = "/get_send_to_info_page/";
		var advert = $(this).data('advert');
		var runner = $(this).data('runner');
		var event_id = $(this).data('event');
		if (typeof advert != 'undefined') {
			if (advert == '1') {
				reg_click(3);
			}
			url += '?advert=' + advert;
		} else if (typeof runner != 'undefined') {
			url += '?runner=' + runner;
		} else if (typeof event_id != 'undefined') {
			url += '?event_id=' + event_id;
		}
		var target = $(this).data('target');
		var submit_url = "/send_message/";
		if (typeof target != 'undefined') {
			submit_url += '?target=' + target;
		}
		$.ajax({
			url: url,
			success: function(msg){
				$('#modalSendLetter').html(msg);
				$('#modalSendLetter').modal();
				$("button#send_letter").click(function(){
					$("button#send_letter").prop("disabled", true);
					$("span#response").html('Отправляем письмо...');
					var formData = new FormData($('form#frm_send_letter')[0]);
					$.ajax({
						type: "POST",
						url: submit_url,
						data: formData,
						contentType: false,
						processData: false,
						success: function(msg){
							$("button#send_letter").prop("disabled", false);
							if (msg.success==1) {
								$('form#frm_send_letter').find("input[type=text], input[type=file], textarea").val("");
								$("span#response").html('Спасибо! Ваше письмо успешно отправлено.');
							} else {
								$("span#response").html('Письмо не отправлено. Ошибка: ' + msg.error);
							}
						},
						error: function(){
							$("button#send_letter").prop("disabled", false);
							$("span#response").html("К сожалению, отправить письмо не получилось. Пожалуйста, попробуйте позже или напишите нам на info@probeg.org.");
						}
					});
				});
			},
			dataType: 'html'
		});
		return false;
	});
	$("a.send_from_info_page").click(function(){
		var url = "/get_send_from_info_page/";
		var ticket_id = $(this).data('ticket');
		var event_id = $(this).data('event');
		var event_participants_id = $(this).data('eventParticipants');
		var event_wo_protocols_id = $(this).data('eventWoProtocols');
		var user_id = $(this).data('user');
		if (typeof ticket_id != 'undefined') {
			url += 'ticket/' + ticket_id + '/';
			var wrong_club = $(this).data('wrongClub');
			if (typeof wrong_club != 'undefined') {
						url += 'wrong_club/';
			}
		} else if (typeof event_id != 'undefined') {
			url += 'event/' + event_id + '/';
		} else if (typeof event_participants_id != 'undefined') {
			url += 'event_participants/' + event_participants_id + '/';
		} else if (typeof event_wo_protocols_id != 'undefined') {
			url += 'event_wo_protocols/' + event_wo_protocols_id + '/';
		} else if (typeof user_id != 'undefined') {
			url += 'user/' + user_id + '/';
		}
		$.ajax({
			url: url,
			success: function(msg){
				$('#modalSendLetter').html(msg);
				$('#modalSendLetter').modal();
				$("button#send_letterAdmin").click(function(){
					$("button#send_letterAdmin").prop("disabled", true);
					$("span#response").html('Отправляем письмо...');
					var formData = new FormData($('form#frm_send_letterAdmin')[0]);
					$.ajax({
						type: "POST",
						url: "/send_message_admin/",
						data: formData,
						contentType: false,
						processData: false,
						success: function(msg){
							if (msg.success==1) {
								// $('form#frm_send_letterAdmin').find("input[type=text], input[type=file], textarea").val("");
								$("span#response").html('Спасибо! Ваше письмо успешно отправлено на адреса: ' + msg.targets);
							} else {
								$("button#send_letterAdmin").prop("disabled", false);
								$("span#response").html('Письмо не отправлено. Ошибка: ' + msg.error);
							}
						},
						error: function(){
							$("button#send_letterAdmin").prop("disabled", false);
							$("span#response").html("К сожалению, отправить письмо не получилось."
								+ " Пожалуйста, попробуйте позже или напишите нам на info@probeg.org.");
						}
					});
				});
			},
			dataType: 'html'
		});
		return false;
	});
	$(".btnAddResult").click(function(){
		var event_id = $(this).data('event')
		$.ajax({
			url: "/get_add_result_page/event/" + event_id + "/",
			success: function(msg){
				$('#modalSendLetter').html(msg);
				$('#modalSendLetter').modal();
				$("button#add_result").click(function(){
					$("button#add_result").prop("disabled", true);
					$("span#response").html('Посылаем запрос...');
					var formData = new FormData($('form#frm_add_result')[0]);
					$.ajax({
						type: "POST",
						url: "/add_unofficial_result/event/" + event_id + "/",
						data: formData,
						contentType: false,
						processData: false,
						success: function(msg){
							$("button#add_result").prop("disabled", false);
							if (msg.success==1) {
								$('form#frm_send_letter').find("input[type=text], input[type=file], textarea").val("");
								response = 'Спасибо! Ваш результат добавлен и ждёт одобрения администраторами.';
								if (msg.can_be_counted_for_klb==1) {
									if (msg.will_be_counted_for_klb==1) {
										response += ' Проверить, когда мы засчитаем его Вам в зачёт КЛБМатча,';
										response += ' Вы можете на странице <a href="' + msg.url_my_results + '">с Вашими результатами.</a>';
									} else {
										response += ' Результат не будет засчитан в КЛБМатч. Причина: ' + msg.reason + '.';
									}
								}
								$("span#response").html(response);
							} else {
								$("span#response").html('Результат не отправлен. Ошибка: ' + msg.error);
							}
						},
						error: function(){
							$("button#add_result").prop("disabled", false);
							$("span#response").html("К сожалению, добавить результат не получилось."
								+ " Пожалуйста, попробуйте позже или напишите нам на info@probeg.org.");
						}
					});
				});
			},
			dataType: 'html'
		});
		return false;
	});
	$(".btnAddEvent").click(function(){
		var series_id = $(this).data('series')
		$.ajax({
			url: "/get_add_event_page/series/" + series_id + "/",
			success: function(msg){
				$('#modalSendLetter').html(msg);
				$('#modalSendLetter').modal();
				$("button#add_event").click(function(){
					$("button#add_event").prop("disabled", true);
					$("span#response").html('Посылаем запрос...');
					var formData = new FormData($('form#frm_add_event')[0]);
					$.ajax({
						type: "POST",
						url: "/add_unofficial_event/series/" + series_id + "/",
						data: formData,
						contentType: false,
						processData: false,
						success: function(msg){
							$("button#add_event").prop("disabled", false);
							if (msg.success==1) {
								$('form#frm_send_letter').find("input[type=text], input[type=file], textarea").val("");
								$("span#response").html('Спасибо! Информация о событии добавлена.');
							} else {
								$("span#response").html('Результат не отправлен. Ошибка: ' + msg.error);
							}
						},
						error: function(){
							$("button#add_event").prop("disabled", false);
							$("span#response").html("К сожалению, добавить забег не получилось."
								+ " Пожалуйста, попробуйте позже или напишите нам на info@probeg.org.");
						}
					});
				});
			},
			dataType: 'html'
		});
		return false;
	});
	$(".btnAddSeries").click(function(){
		var series_id = $(this).data('series')
		$.ajax({
			url: "/get_add_series_page/",
			success: function(msg){
				$('#modalSendLetter').html(msg);
				initCities();
				$('#modalSendLetter').modal();
				$("button#add_series").click(function(){
					$("button#add_series").prop("disabled", true);
					$("span#response").html('Посылаем запрос...');
					var formData = new FormData($('form#frm_add_series')[0]);
					$.ajax({
						type: "POST",
						url: "/add_unofficial_series/",
						data: formData,
						contentType: false,
						processData: false,
						success: function(msg){
							$("button#add_series").prop("disabled", false);
							if (msg.success==1) {
								$('form#frm_send_letter').find("input[type=text], input[type=file], textarea").val("");
								$("span#response").html('Спасибо! Страница созданного события: <a href="'
									+ msg.link + '">' + msg.link + '</a>.');
								yaCounter38500270.reachGoal('NewRunSubmitted');
							} else {
								$("span#response").html('Результат не отправлен. Ошибка: ' + msg.error);
							}
						},
						error: function(){
							$("button#add_series").prop("disabled", false);
							$("span#response").html("К сожалению, добавить результат не получилось."
								+ " Пожалуйста, попробуйте позже или напишите нам на info@probeg.org.");
						}
					});
				});
			},
			dataType: 'html'
		});
		return false;
	});
	$("a.add_review_page").click(function(){
		var event_id = $(this).data('event');
		var photo = $(this).data('photo');
		my_url = "/get_add_review_page/event/" + event_id + "/";
		if (photo == "1") {
			my_url += "photo/"
		}
		$.ajax({
			url: my_url,
			success: function(msg){
				$('#modalSendLetter').html(msg);
				$('#modalSendLetter').modal();
				$("button#send_letter").click(function(){
					$("button#send_letter").prop("disabled", true);
					$("span#response").html('Отправляем письмо...');
					var formData = new FormData($('form#frm_add_review')[0]);
					$.ajax({
						type: "POST",
						url: "/add_review/",
						data: formData,
						contentType: false,
						processData: false,
						success: function(msg){
							$("button#send_letter").prop("disabled", false);
							if (msg.success == 1) {
								$('form#frm_send_letter').find("input[type=text], input[type=file], textarea").val("");
								$("span#response").html('Спасибо! Теперь Вы можете увидеть новую ссылку на странице забега <a href="'
									+ msg.link + '">' + msg.link + '</a>.');
							} else {
								$("span#response").html('Письмо не отправлено. Ошибка: ' + msg.error);
							}
						},
						error: function(){
							$("button#send_letter").prop("disabled", false);
							$("span#response").html("К сожалению, отправить письмо не получилось. Пожалуйста, попробуйте позже или напишите нам на info@probeg.org.");
						}
					});
				});
			},
			dataType: 'html'
		});
		return false;
	});
	$(".showAvatar").click(function(){
		var user_id = $(this).data('user');
		$.ajax({
			url: "/get_avatar/user/" + user_id + "/",
			success: function(msg){
				$('#modalSendLetter').html(msg);
				$('#modalSendLetter').modal();
			},
			dataType: 'html'
		});
		return false;
	});
	$(".showLogo").click(function(){
		var event_id = $(this).data('event');
		var organizer_id = $(this).data('organizer');
		if (typeof event_id != 'undefined') {
			url_link = "/logo/event/" + event_id;
		} else if (typeof organizer_id != 'undefined') {
			url_link = "/logo/organizer/" + organizer_id;
		} else {
			var series_id = $(this).data('series');
			url_link = "/logo/series/" + series_id;
		}
		$.ajax({
			url: url_link,
			success: function(msg){
				$('#modalSendLetter').html(msg);
				$('#modalSendLetter').modal();
			},
			dataType: 'html'
		});
		return false;
	});
	if (isIEorEDGE()) {
		$("button.btn-pagination").click(function(){
			$('<input />').attr('type', 'hidden').attr('name', 'page').attr('value', this.value).appendTo('#frmSearch');
			$('#frmSearch').submit();
		});
		$("button.btn-ordering").click(function(){
			$('<input />').attr('type', 'hidden').attr('name', 'new_ordering').attr('value', this.value).appendTo('#frmSearch');
			$('#frmSearch').submit();
		});
	}
	$(".del-from-match").change(function(){
		result_id = $(this).data('result');
		chkbox_to_delete = $("#to_unclaim_" + result_id);
		if (this.checked) {
			chkbox_to_delete.prop("disabled", false);
			chkbox_to_delete.prop("checked", true);
		} else {
			chkbox_to_delete.prop("checked", false);
			chkbox_to_delete.prop("disabled", true);
		}
	});
	$("#chkIsResponsible").click(function(e) {
		$("#btnSubmit").prop("disabled", !(this.checked));
	});
});

function claim_result(link, name, race_name, race_distance, result) {
	var retVal = prompt("Результат " + result + " на забеге «"
		+ race_name + "» на дистанцию " + race_distance + " под именем «" + name
		+ "» – действительно ваш? Если да, но при этом имя отличается от каждого из ваших, "
		+ "рекомендуем оставить комментарий администраторам.");
	if (retVal != null)
		window.location = link + "?comment=" + encodeURIComponent(retVal);
}

function unclaim_result(link, name, race_name, race_distance, result) {
	var retVal = prompt("Вы действительно хотите отказаться от результата " + result + " на забеге «"
		+ race_name + "» на дистанцию " + race_distance + " под именем «" + name + "»? Будет здорово, если напишете комментарий – "
		+" например, что Вы не бежали в этом забеге или что просто не хотите видеть его на своей странице.");
	if (retVal != null)
		window.location = link + "?comment=" + encodeURIComponent(retVal);
}

function plural_ending(value, endings) {
	value %= 100;
	if (10 < value && value < 20) {return endings[2]}
	value %= 10;
	if (value == 0) {return endings[2]}
	if (value == 1) {return endings[0]}
	if (value >= 5) {return endings[2]}
	return endings[1];
}

function unclaim_results() {
	var n_results = $(".chkbox:checked").length;
	if (n_results == 0) {return false}
	var retVal = prompt("Вы действительно хотите отказаться от " + n_results + " результат" + plural_ending(n_results, ["а", "ов", "ов"])
		+ "? Будет здорово, если напишете комментарий – "
		+" например, что Вы не бежали в этих забегах или просто не хотите видеть их на своей странице.");
	if (retVal != null) {
		$('<input />').attr('type', 'hidden').attr('name', 'comment').attr('value', retVal).appendTo('#frmUnclaim');
		document.forms['frmUnclaim'].submit();
	}
}

function confirm_link(question, link) {
	if (confirm(question) == true) {
		window.location = link;
	}
}

function delete_unofficial_result(link, race_name, race_distance, result) {
	confirm_link("Вы действительно хотите удалить неофициальный результат " + result + " на забеге «"
		+ race_name + "» на дистанцию " + race_distance + "?", link);
}

function isIEorEDGE() {
  return (navigator.appName == 'Microsoft Internet Explorer') || (navigator.appName == "Netscape" && navigator.appVersion.indexOf('Trident') > -1);
}

function submitSearchForm(page) {
	if ($('#id_page').length) {
		$('#id_page').val(page);
	} else {
		$('<input />').attr('type', 'hidden').attr('name', 'page').attr('value', page).appendTo('form#frmSearch');
	}
	$('form#frmSearch').submit();
}

function reg_click(ad_id) {
	var oReq = new XMLHttpRequest();
	oReq.open("get", "https://probeg.org/editor/reg_click/" + ad_id + "/", true);
	oReq.send();
}