// var w = 800;
// var w = window.innerWidth / 2;
var w = parseInt(d3.select("#plotParent").style("width")) - parseInt(d3.select("#plotParent").style("padding-left"))
	 - parseInt(d3.select("#plotParent").style("padding-right")) - 20;
var h = 300;
var padding = 20;
var padding_right = 150;
var col_padding = 1;
var pace_label_width = 40;
var pace_label_height = 10;
var pace_label_v_padding = 20;
var max_pace_secs, min_pace_secs;
var paces = [];
var lengths = [];
var segment_left = [];
var segment_width = [];
var segment_center = [];
var segment_height = [];
var segment_top = [];

function pad(num, size) {
    var s = num.toString();
    while (s.length < size) s = "0" + s;
    return s;
}

function strPace(secs) { // 80 to "1:20/км"
	secs = Math.floor(secs);
	minutes = Math.floor(secs/60);
	seconds = secs % 60;
	return minutes.toString() + ":" + pad(seconds, 2) + "/км";
}

function getPace(length, split, distance_type) { // in secs/km
	if (distance_type == 1) {
		 return split * 10. / length;
	} else {
		 return length * 60000. / split;
	}
}

function calcPaces(splits, distance_type) {
	curLength = 0;
	curMax = 0;
	curMin = 1000;
	for (var i = 0; i < splits.length - 1; i++) {
		lengths[i] = splits[i+1][0] - splits[i][0];
		paces[i] = getPace(lengths[i], splits[i+1][1] - splits[i][1], distance_type);
		if (paces[i] > curMax) curMax = paces[i];
		if (paces[i] < curMin) curMin = paces[i];
	}
	max_pace_secs = (Math.ceil(curMax / 30) + 0.1) * 30;
	min_pace_secs = (Math.floor(curMin / 30) - 0.25) * 30;
}

function draw_plot(splits, distance_type) {
	var svgContainer = d3.select("#plot").append("svg").attr("width", w).attr("height", h);
	calcPaces(splits, distance_type);
	// var max_pace_secs = 400;
	// var min_pace_secs = 180;
	length = splits[splits.length - 1][0];
	duration = splits[splits.length - 1][1];
	var xScale = d3.scaleLinear()
		.domain([0, length])
		.range([padding, w - padding_right]);
	var yScale = d3.scaleLinear()
		.domain([min_pace_secs, max_pace_secs])
		.range([h - padding, padding]);
	var xCoef = (w - padding - padding_right) / length;
	var yCoef = (h - 2 * padding) / (max_pace_secs - min_pace_secs);

	avg_pace = getPace(length, duration, distance_type);
	avg_pace_scaled = yScale(avg_pace);
	// svgContainer.append("text")
	// 	.attr("font-family", "sans-serif")
	// 	.attr("font-size", "12px")
	// 	.attr("fill", "black")
	// 	.text("Средний темп:" + strPace(avg_pace))
	// 	.attr("x", xScale(0) + 10)
	// 	.attr("y", avg_pace_scaled - 10);

	for (var i = 0; i < splits.length - 1; i++) {
		segment_left[i] = xScale(splits[i][0]) + col_padding;
		segment_width[i] = lengths[i] * xCoef - (2 * col_padding);
		segment_center[i] = segment_left[i] + segment_width[i] / 2;
		segment_height[i] = (paces[i] - min_pace_secs) * yCoef;
		segment_top[i] = yScale(min_pace_secs) - segment_height[i];
		svgContainer.append("rect")
			.attr("x", segment_left[i])
			.attr("y", segment_top[i])
			.attr("width", segment_width[i])
			.attr("height", segment_height[i])
			// .attr("stroke", "black")
			// .attr("stroke-width", "2")
			// .attr("opacity", "0.75")
			.attr("fill", "orange");
	}
		// svgContainer.append("circle")
		// 	.attr("cx", segment_center)
		// 	.attr("cy", segment_top)
		// 	.attr("r", 3)
			// .attr("fill", "#2e6da4");
	for (var i = 0; i < splits.length - 1; i++) {
		if (segment_width[i] < pace_label_width) {
		// if (0) {
		svgContainer.append("text")
			.attr("font-family", "sans-serif")
			.attr("font-size", "14px")
			.attr("fill", "black")
			.text(strPace(paces[i]))
			// .attr("x", segment_center - pace_label_height / 2)
			// .attr("y", segment_top + pace_label_v_padding)
			.attr("text-anchor", "middle")
			.attr("transform", "translate(" + (segment_center[i] - 5) + "," + (yScale(min_pace_secs) - 2 * pace_label_v_padding) + ") rotate(90)");
		} else {
			text_y = (
				((segment_top[i] < avg_pace_scaled) && (segment_top[i] > avg_pace_scaled - pace_label_v_padding))
					// || (segment_width < pace_label_width)
					) ?
				segment_top[i] - pace_label_v_padding / 3 : segment_top[i] + pace_label_v_padding;
			svgContainer.append("text")
				.attr("font-family", "arial")
				.attr("font-size", "14px")
				.attr("fill", "black")
				.text(strPace(paces[i]))
				.attr("text-anchor", "middle")
				.attr("x", segment_center[i])
				.attr("y", text_y);
				// .attr("y", yScale(min_pace_secs) - pace_label_v_padding)
		}	
	}
	svgContainer.append("line")
		.attr("x1", xScale(0) + col_padding)
		.attr("y1", avg_pace_scaled)
		.attr("x2", w)
		.attr("y2", avg_pace_scaled)
		// .attr("stroke-width", "1")
		// .attr("opacity", "0.5")
		.attr("class", "overall_pace")
		.attr("stroke", "black");
	svgContainer.append("text")
		.attr("font-family", "arial")
		.attr("font-size", "14px")
		.attr("fill", "black")
		.attr("text-anchor", "middle")
		.text("Средний темп:")
		.attr("x", w - padding_right / 2)
		.attr("y", avg_pace_scaled + pace_label_v_padding);
	svgContainer.append("text")
		.attr("font-family", "arial")
		.attr("font-size", "14px")
		.attr("fill", "black")
		.attr("text-anchor", "middle")
		.text(strPace(avg_pace))
		.attr("x", w - padding_right / 2)
		.attr("y", avg_pace_scaled + pace_label_v_padding + 17);
	lengths = [];
	for (var i = 0; i < splits.length; i++) {
		lengths[i] = splits[i][0];
	}
	var xAxis = d3.axisBottom(xScale)
		.tickValues(lengths)
		.tickFormat(d3.format(".2s"));
	svgContainer.append("g")
		.attr("class", "axis")
		.attr("transform", "translate(0," + (h - padding) + ")")
		.call(xAxis);
}