if (redirector === undefined) {
    var redirector = {};
}

//////////////////////////////////////////////////////////
// Client-side URL transformation function.
redirector.xform = function(url, hash, full_or_path) {
    if (!!url && url != "(invalid input)") {
        if (hash.match(/^#_ncbi_dlg_cpyrght_.*$/)) {
            // copyright hash
            url = "";
            if (full_or_path == "full") {
                url = "http://www.ncbi.nlm.nih.gov";
            }
            url += "/About/disclaimer.html";
        } else if (url.indexOf("#") == -1) {
            // no server-side hash - use client-side hash
            url += hash;
        } else {
            // In general, don't replace a server-side hash with a
            // client-side hash.  However, table footnotes are a special case
            // where the server creates a hash for the table but is unaware
            // that it can be refined to the table footnote.
            // For example:
            // incoming: /books/n/toolkit/ch_libconfig/table/ch_libconfig.T8/?report=objectonly#__pp_ch_libconfig_TF_24
            // transformed by server: /toolkit/doc/book/ch_libconfig/?report=objectonly#ch_libconfig.T8
            // transformed by client: /toolkit/doc/book/ch_libconfig/?report=objectonly#ch_libconfig.TF.24
            var match_client = /^#__pp_([a-zA-Z0-9_.-]+)_TF_([0-9]+)$/.exec(hash);
            if (match_client) {
                var client_id = match_client[2];
                var match_server = /^(.*\.T)([0-9]+)$/.exec(url);
                if (match_server) {
                    var server_sans_id = match_server[1];
                    url = server_sans_id + "F." + client_id;
                }
            }
        }
    }
    return url;
};

//////////////////////////////////////////////////////////
// Client-side function to do stuff that couldn't be done on the server-side.
// Show / hide stuff; finalize data; possibly alter and then encode old and new URLs.
redirector.finalizePage = function() {
    // Grab server-side generated data from meta tags and put into JS variables.
    redirector.old_url  = unescape(document.getElementById("meta_old_url").content);
    redirector.new_url  = unescape(document.getElementById("meta_new_url").content);

    // If the browser has a hash, then:
    //  (a) add it to the old URL.
    //  (b) possibly alter the new URL.
    if (window.location.hash) {
        redirector.old_url += window.location.hash;

        // Possibly alter new URL (if there is one), depending on browser hash value and server-side computed hash.
        redirector.new_url = redirector.xform(redirector.new_url, window.location.hash, "full");
    } else {
        // no hash
    }

    // Set the URLs.
    document.getElementById("old_url").innerHTML = redirector.old_url;
    //
    document.getElementById("new_url").setAttribute("href", redirector.new_url);
    document.getElementById("new_url").innerHTML = redirector.new_url;
};

// Make it all happen.
redirector.finalizePage();
