if(redirector === undefined) {
    var redirector = {};
}

redirector.htmlEncode = function(html) {
// this double-encodes
//    return html.replace("&", "&amp;").replace("<", "&lt;");

    // this doesn't work for IE
    //return document.createElement('dummy').appendChild(document.createTextNode(html)).parentNode.innerHTML;

    // just do it manually
    var html_encoded = "";
    for (var idx = 0; idx < html.length; ++idx) {
        if (html.charAt(idx) == "&") {
            html_encoded += "&amp;";
        } else if (html.charAt(idx) == "<") {
            html_encoded += "&lt;";
        } else {
            html_encoded += html.charAt(idx);
        }
    }
    return html_encoded;
};

redirector.htmlDecode = function(html) {
    // this doesn't work for IE
//    var a = document.createElement('a');
//    a.innerHTML = html;
//    return a.textContent;

    // just do it manually
    var html_decoded = "";
    for (var idx = 0; idx < html.length; ) {
        var num = 0;
        if (html.substring(idx, idx+5) == "&amp;") {
            html_decoded += "&";
            num = 5;
        } else if (html.substring(idx, idx+4) == "&lt;") {
            html_decoded += "<";
            num = 4;
        } else {
            html_decoded += html.charAt(idx);
            num = 1;
        }
        idx += num;
    }
    return html_decoded;
};

//////////////////////////////////////////////////////////
// Client-side function to do stuff that couldn't be done on the server-side.
// Show / hide stuff; finalize data; possibly alter and then encode old and new URLs.
redirector.finalizeTests = function() {
    // Grab server-side generated data from meta tags and put into JS variables.
    redirector.scheme       = unescape(document.getElementById("meta_scheme").content);
    redirector.server_name  = unescape(document.getElementById("meta_server_name").content);

    // Indicate that we are using JavaScript.
    var elem = document.getElementById("debug_javascript");
    if (elem) {
        elem.innerHTML = "yes";
    }

    // Record the browser hash:
    var elem = document.getElementById("debug_fragment");
    if (elem) {
        if (window.location.hash) {
            elem.innerHTML = window.location.hash;
        } else {
            elem.innerHTML = "";
        }
    }

    // Transform test URLs.
    var test_ids = document.getElementsByClassName("test-id");
    for (var idx=0; idx < test_ids.length; ++idx) {
        id_str = test_ids[idx].innerHTML;
        var e_in = document.getElementById("url_in_" + id_str);
        var e_trans = document.getElementById("url_trans_" + id_str);
        var e_out_exp = document.getElementById("url_out_exp_" + id_str);
        var e_out_got = document.getElementById("client_url_got_" + id_str);
        var url_in = e_in.innerHTML;
        var hash = ""
        var hash_pos = url_in.indexOf("#");
        if (hash_pos != -1) {
            hash = url_in.substring(hash_pos);
        }
        var url_out = redirector.xform(redirector.htmlDecode(e_trans.innerHTML), hash, "path");
        var esc_url_out = redirector.htmlEncode(url_out);
        var span_out = "<a href=\"" + redirector.scheme + "://" + redirector.server_name + esc_url_out + "\">" + esc_url_out + "</a>";
        e_out_got.innerHTML = span_out;
        if (e_out_exp.innerHTML == esc_url_out) {
            e_out_got.className = "test-pass";
        } else {
            e_out_got.className = "test-fail";
        }
    }
};

// Make it all happen.
redirector.finalizeTests();
