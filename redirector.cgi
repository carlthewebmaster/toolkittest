#!/bin/env python
# coding: utf-8
# $Id: redirector.cgi 450748 2014-10-30 14:18:57Z mcelhany $
# Authors: David McElhany
# Audience: NCBI Internal

"""
The C++ Toolkit book used to be hosted on the NCBI Bookshelf.  However, because
it was significantly different from the other books in that collection, it
presented frequent maintenance annoyances for the Bookshelf folks.  It was
therefore decided to move the Toolkit book out of the Bookshelf system.

However, there are numerous sources of links to the old book - search engine
results, hard-coded URLs in web pages, and people's bookmarks.  Therefore, it
is necessary to redirect old book requests to the new book.  There are two
reasons this is not done with a simple redirect directive on the web server:
1.  There is not a direct one-to-one correspondence between old book URLs and
    new book URLs.  The correspondence will deteriorate as the new book changes.
2.  Simple redirection will not inform users of the change.  A "redirector"
    page will inform them of the change and request that they make updates
    to their bookmarks and/or help get referring web pages changed.

This redirector CGI serves the following functions:
1.  Act as the recipient of all redirections from the old Toolkit book.
2.  Integrate server-side (e.g. requested URL) and client-side (fragment)
    to determine the best-guess for the new book URL that most closely matches
    the requested old book URL.
3.  Generate a web page that provides information on the originally requested
    URL, the closest-match new book URL, and related info.
4.  Link to the closest-match new book URL and the new book TOC.

In the case of links to the main page of the book, do not display the redirector
page because (a) this is a bit of a nuissance for people that don't need to
change URLs, and (b) not redirecting results in the redirector page getting top
billing in search engine results, and redirecting instead will fix that.

"""


import cgi, httplib, os, re, sys, urllib, urlparse

INVALID_INPUT = "(invalid input)"


class RedirEx(Exception):
    "Redirector exception base class"
    def __init__(self, message):
        super(RedirEx, self).__init__(message)
        self.message = message

class RedirEx_ApparentInvalidPage(RedirEx):
    "Redirector exception - for an apparently invalid page"
    def __init__(self, message):
        super(RedirEx_ApparentInvalidPage, self).__init__(message)
        self.message = message

class RedirEx_PageNotFoundInUrl(RedirEx):
    "Redirector exception - for a URL that doesn't appear to contain a page"
    def __init__(self, message):
        super(RedirEx_PageNotFoundInUrl, self).__init__(message)
        self.message = message

class RedirEx_UnrecognizedUrlPattern(RedirEx):
    "Redirector exception - for an unrecognized URL"
    def __init__(self, message):
        super(RedirEx_UnrecognizedUrlPattern, self).__init__(message)
        self.message = message


class Redirector(object):
    "Encapsulate data and functionality related to redirecting old URLs."

    # Response types:
    RT_AUTO = "auto"
    RT_BAD  = "bad"
    RT_INFO = "info"

    # Transform ID:
    XFORM_ID = -1

    def __init__(self):

        # Find the referer (if one).
        self.__referer_esc = cgi.escape(os.environ["HTTP_REFERER"]) if "HTTP_REFERER" in os.environ.keys() else ""

        # Find the request method.
        self.method = os.environ["REQUEST_METHOD"].upper() if "REQUEST_METHOD" in os.environ.keys() else "(none)"

        # We expect the old book URLs to be redirected from the Bookshelf system
        # and to contain a 'url' parameter containing the encoded original
        # REQUEST_URI.
        params_redir = urlparse.parse_qs(os.environ["QUERY_STRING"] if "QUERY_STRING" in os.environ.keys() else "", keep_blank_values=True)
        path_info = ""
        query_string = ""
        frag_string = ""
        params_orig = {}
        if "url" in params_redir.keys():
            url = urllib.unquote(params_redir["url"][0])
            match = re.match(r"\A([^?#]+)([?][^#]*|)(#.*|)\Z", url)
            if match:
                path_info = match.group(1)
                if match.group(2) and len(match.group(2)) > 1:
                    query_string = match.group(2)
                    params_orig = urlparse.parse_qs(query_string[1:], keep_blank_values=True)
                if match.group(3) and len(match.group(3)) > 1:
                    frag_string = match.group(3)
        self.__scheme = "https" if "HTTPS" in os.environ.keys() else "http"
        self.__server_name = os.environ["SERVER_NAME"]
        self.__old_url_esc = cgi.escape(self.__scheme + "://" + self.__server_name + path_info + query_string + frag_string)
        self.__old_url_given = True if path_info + query_string + frag_string else False

        # Create the outgoing URL (prior to possible client-side fragment analysis and final URL transformation).
        dev = True if re.match(r"\A(i|m|intra)?(web)?dev[0-9]*.ncbi.nlm.nih.gov\Z", self.__server_name) else False
        if dev:
            self.__net_loc = "dev.ncbi.nlm.nih.gov"
        else:
            self.__net_loc = self.__server_name
        self.__net_loc_esc = cgi.escape(self.__net_loc)
        #self.__toc_loc_esc = cgi.escape(self.__scheme + "://" + self.__net_loc + "/toolkit/doc/book/")
        self.__toc_loc_esc = cgi.escape(self.__scheme + "://www.ncbi.nlm.nih.gov/toolkit/doc/book/")
        try:
            self.__xform_idx = ""
            self.__xform_rt  = ""
            self.__xform_pat = ""
            self.__xform_rep = ""
            self.__xform_str = ""
            self.__xform_res = ""
            self.__xform_groups = []
            self.resp_type = Redirector.RT_INFO # may be changed by xform() below
            new_path = self.xform(path_info + query_string, True)
            self.__new_url_esc = cgi.escape(self.__scheme + "://" + self.__net_loc + new_path)

            # Verify the new book URL before presenting it to the user.
            if Redirector.get_url_final_status_parts(self.__scheme + "://", self.__net_loc, new_path) != 200:
                self.__new_url_esc = ""
                self.resp_type = Redirector.RT_BAD
        except RedirEx as ex:
            self.__new_url_esc = ""
            self.resp_type = Redirector.RT_BAD

        # Find out if testing or debugging was requested (dev only).
        if dev and ("redirector_debug" in params_redir.keys() or "redirector_debug" in params_orig.keys()):
            self.__debug_mode = True
        else:
            self.__debug_mode = False

        # Perform transformation testing, if requested.
        if self.__debug_mode:
            # Test case fields:
            #   0: test alias
            #   1: input page - expected
            #   2: input page - actual
            #   3: output page - expected
            #   4: output page - actual
            #   5: server-side output url - expected
            #   6: server-side output url - actual
            #   7: client-side output url - expected
            self.__tests = {

                # invalid patterns - wrong case
                "/books/N/toolkit": ["a1", INVALID_INPUT, "", "", "", "", "", ""],
                "/books/n/toolkit/ToC": ["a2", INVALID_INPUT, "", "", "", "", "", ""],
                "/books/nbk7160": ["a3", INVALID_INPUT, "", "", "", "", "", ""],

                # invalid patterns - junk
                "/books/NBK716000000000": ["b1", INVALID_INPUT, "", "", "", "", "", ""],
                "/books/n/NBK7160": ["b2", INVALID_INPUT, "", "", "", "", "", ""],
                "/books/n/Toolkit": ["b3", INVALID_INPUT, "", "", "", "", "", ""],
                "/Books/n/toolkit": ["b4", INVALID_INPUT, "", "", "", "", "", ""],
                "/books/n/toolkittoc": ["b5", INVALID_INPUT, "", "", "", "", "", ""],
                "/books/n/toc": ["b6", INVALID_INPUT, "", "", "", "", "", ""],
                "/books/n/toolkit/NBK7199/box/ch_cgi.cgi_cpp.html/?report=objectonly": ["b7", INVALID_INPUT, "", "", "", "", "", ""],
                "/books/n/toolkit/garbage": ["b8", INVALID_INPUT, "", "", "", "", "", ""],
                "/books/n/toolkit/toc/toc": ["b9", INVALID_INPUT, "", "", "", "", "", ""],

                # toc
                "/books/NBK7160": ["d1", "/books/NBK7160", "", "toc", "", "/toolkit/doc/book/", "", "/toolkit/doc/book/"],
                "/books/NBK7160?": ["d2", "/books/NBK7160", "", "toc", "", "/toolkit/doc/book/?", "", "/toolkit/doc/book/?"],
                "/books/NBK7160?asdf": ["d3", "/books/NBK7160", "", "toc", "", "/toolkit/doc/book/?asdf", "", "/toolkit/doc/book/?asdf"],
                "/books/NBK7160?asdf=qwer": ["d4", "/books/NBK7160", "", "toc", "", "/toolkit/doc/book/?asdf=qwer", "", "/toolkit/doc/book/?asdf=qwer"],
                "/books/NBK7160/": ["d5", "/books/NBK7160", "", "toc", "", "/toolkit/doc/book/", "", "/toolkit/doc/book/"],
                "/books/NBK7160/?": ["d6", "/books/NBK7160", "", "toc", "", "/toolkit/doc/book/?", "", "/toolkit/doc/book/?"],
                "/books/NBK7160/?asdf": ["d7", "/books/NBK7160", "", "toc", "", "/toolkit/doc/book/?asdf", "", "/toolkit/doc/book/?asdf"],
                "/books/NBK7160/?asdf=qwer": ["d8", "/books/NBK7160", "", "toc", "", "/toolkit/doc/book/?asdf=qwer", "", "/toolkit/doc/book/?asdf=qwer"],
                "/books/n/toolkit": ["d9", "/books/n/toolkit", "", "toc", "", "/toolkit/doc/book/", "", "/toolkit/doc/book/"],
                "/books/n/toolkit?": ["d10", "/books/n/toolkit", "", "toc", "", "/toolkit/doc/book/?", "", "/toolkit/doc/book/?"],
                "/books/n/toolkit?asdf": ["d11", "/books/n/toolkit", "", "toc", "", "/toolkit/doc/book/?asdf", "", "/toolkit/doc/book/?asdf"],
                "/books/n/toolkit?asdf=qwer": ["d12", "/books/n/toolkit", "", "toc", "", "/toolkit/doc/book/?asdf=qwer", "", "/toolkit/doc/book/?asdf=qwer"],
                "/books/n/toolkit/": ["d13", "/books/n/toolkit", "", "toc", "", "/toolkit/doc/book/", "", "/toolkit/doc/book/"],
                "/books/n/toolkit/?": ["d14", "/books/n/toolkit", "", "toc", "", "/toolkit/doc/book/?", "", "/toolkit/doc/book/?"],
                "/books/n/toolkit/?asdf": ["d15", "/books/n/toolkit", "", "toc", "", "/toolkit/doc/book/?asdf", "", "/toolkit/doc/book/?asdf"],
                "/books/n/toolkit/?asdf=qwer": ["d16", "/books/n/toolkit", "", "toc", "", "/toolkit/doc/book/?asdf=qwer", "", "/toolkit/doc/book/?asdf=qwer"],
                "/books/n/toolkit/toc": ["d17", "/books/n/toolkit/toc", "", "toc", "", "/toolkit/doc/book/", "", "/toolkit/doc/book/"],
                "/books/n/toolkit/toc?": ["d18", "/books/n/toolkit/toc", "", "toc", "", "/toolkit/doc/book/?", "", "/toolkit/doc/book/?"],
                "/books/n/toolkit/toc?asdf": ["d19", "/books/n/toolkit/toc", "", "toc", "", "/toolkit/doc/book/?asdf", "", "/toolkit/doc/book/?asdf"],
                "/books/n/toolkit/toc?asdf=qwer": ["d20", "/books/n/toolkit/toc", "", "toc", "", "/toolkit/doc/book/?asdf=qwer", "", "/toolkit/doc/book/?asdf=qwer"],
                "/books/n/toolkit/toc/": ["d21", "/books/n/toolkit/toc", "", "toc", "", "/toolkit/doc/book/", "", "/toolkit/doc/book/"],
                "/books/n/toolkit/toc/?": ["d22", "/books/n/toolkit/toc", "", "toc", "", "/toolkit/doc/book/?", "", "/toolkit/doc/book/?"],
                "/books/n/toolkit/toc/?asdf": ["d23", "/books/n/toolkit/toc", "", "toc", "", "/toolkit/doc/book/?asdf", "", "/toolkit/doc/book/?asdf"],
                "/books/n/toolkit/toc/?asdf=qwer": ["d24", "/books/n/toolkit/toc", "", "toc", "", "/toolkit/doc/book/?asdf=qwer", "", "/toolkit/doc/book/?asdf=qwer"],

                # PDFs
                "/books/n/toolkit/pdf/TOC.pdf": ["e1", "/books/n/toolkit/toc", "", "toc", "", "/toolkit/doc/book/pdf/TOC.pdf", "", "/toolkit/doc/book/pdf/TOC.pdf"],
                "/books/n/toolkit/toc/pdf/TOC.pdf": ["e2", "/books/n/toolkit/toc", "", "toc", "", "/toolkit/doc/book/pdf/TOC.pdf", "", "/toolkit/doc/book/pdf/TOC.pdf"],
                "/books/n/toolkit/app1.appendix1/pdf/app1.appendix1.pdf": ["e3", "/books/n/toolkit/app1.appendix1", "", "app1.appendix1", "", "/toolkit/doc/book/pdf/app1.pdf", "", "/toolkit/doc/book/pdf/app1.pdf"],
                "/books/n/toolkit/toolkit.fm/pdf/fm.pdf": ["e4", "/books/n/toolkit/toolkit.fm", "", "toolkit.fm", "", "/toolkit/doc/book/pdf/fm.pdf", "", "/toolkit/doc/book/pdf/fm.pdf"],
                "/books/n/toolkit/toolkit.fm/pdf/toolkit.fm.pdf": ["e5", "/books/n/toolkit/toolkit.fm", "", "toolkit.fm", "", "/toolkit/doc/book/pdf/fm.pdf", "", "/toolkit/doc/book/pdf/fm.pdf"],
                "/books/n/toolkit/ch_devtools/pdf/ch_devtools.pdf": ["e6", "/books/n/toolkit/ch_devtools", "", "ch_devtools", "", "/toolkit/doc/book/pdf/ch_devtools.pdf", "", "/toolkit/doc/book/pdf/ch_devtools.pdf"],
                "/books/n/toolkit/ch_intro/pdf/ch_intro.pdf": ["e7", "/books/n/toolkit/ch_intro", "", "ch_intro", "", "/toolkit/doc/book/pdf/ch_intro.pdf", "", "/toolkit/doc/book/pdf/ch_intro.pdf"],
                "/books/n/toolkit/app1.appendix1/pdf/app1.pdf": ["e8", "/books/n/toolkit/app1.appendix1", "", "app1.appendix1", "", "/toolkit/doc/book/pdf/app1.pdf", "", "/toolkit/doc/book/pdf/app1.pdf"],
                #
                "/books/NBK7160/pdf/TOC.pdf": ["f1", "/books/NBK7160", "", "toc", "", "/toolkit/doc/book/pdf/TOC.pdf", "", "/toolkit/doc/book/pdf/TOC.pdf"],
                "/books/NBK7155/pdf/app1.appendix1.pdf": ["f2", "/books/NBK7155", "", "app1.appendix1", "", "/toolkit/doc/book/pdf/app1.pdf", "", "/toolkit/doc/book/pdf/app1.pdf"],
                "/books/NBK22952/pdf/fm.pdf": ["f3", "/books/NBK22952", "", "toolkit.fm", "", "/toolkit/doc/book/pdf/fm.pdf", "", "/toolkit/doc/book/pdf/fm.pdf"],
                "/books/NBK22952/pdf/toolkit.fm.pdf": ["f4", "/books/NBK22952", "", "toolkit.fm", "", "/toolkit/doc/book/pdf/fm.pdf", "", "/toolkit/doc/book/pdf/fm.pdf"],
                "/books/NBK7161/pdf/ch_devtools.pdf": ["f5", "/books/NBK7161", "", "ch_devtools", "", "/toolkit/doc/book/pdf/ch_devtools.pdf", "", "/toolkit/doc/book/pdf/ch_devtools.pdf"],
                "/books/NBK7184/pdf/ch_intro.pdf": ["f6", "/books/NBK7184", "", "ch_intro", "", "/toolkit/doc/book/pdf/ch_intro.pdf", "", "/toolkit/doc/book/pdf/ch_intro.pdf"],
                "/books/NBK7155/pdf/app1.pdf": ["f7", "/books/NBK7155", "", "app1.appendix1", "", "/toolkit/doc/book/pdf/app1.pdf", "", "/toolkit/doc/book/pdf/app1.pdf"],

                # images
                "/books/n/toolkit/ch_app/bin/LoadBalancingLocal.jpg": ["g1", "/books/n/toolkit/ch_app", "", "ch_app", "", "/toolkit/doc/book/img/LoadBalancingLocal.jpg", "", "/toolkit/doc/book/img/LoadBalancingLocal.jpg"],
                "/books/NBK7146/bin/LoadBalancingLocal.jpg": ["g2", "/books/NBK7146", "", "ch_app", "", "/toolkit/doc/book/img/LoadBalancingLocal.jpg", "", "/toolkit/doc/book/img/LoadBalancingLocal.jpg"],

                # floating boxes
                "/books/n/toolkit/ch_cgi/box/ch_cgi.cgi_cpp.html/?report=objectonly": ["h1", "/books/n/toolkit/ch_cgi", "", "ch_cgi", "", "/toolkit/doc/book/ch_cgi/?report=objectonly#ch_cgi.cgi_cpp.html", "", "/toolkit/doc/book/ch_cgi/?report=objectonly#ch_cgi.cgi_cpp.html"],
                "/books/NBK7199/box/ch_cgi.cgi_cpp.html/?report=objectonly": ["h2", "/books/NBK7199", "", "ch_cgi", "", "/toolkit/doc/book/ch_cgi/?report=objectonly#ch_cgi.cgi_cpp.html", "", "/toolkit/doc/book/ch_cgi/?report=objectonly#ch_cgi.cgi_cpp.html"],

                # floating figures
                "/books/n/toolkit/ch_intro/figure/ch_intro.F1/?report=objectonly": ["i1", "/books/n/toolkit/ch_intro", "", "ch_intro", "", "/toolkit/doc/book/ch_intro/?report=objectonly#ch_intro.F1", "", "/toolkit/doc/book/ch_intro/?report=objectonly#ch_intro.F1"],
                "/books/n/toolkit/ch_app/figure/ch_app.specs_asn/?report=objectonly": ["i2", "/books/n/toolkit/ch_app", "", "ch_app", "", "/toolkit/doc/book/ch_app/?report=objectonly#ch_app.specs_asn", "", "/toolkit/doc/book/ch_app/?report=objectonly#ch_app.specs_asn"],
                "/books/n/toolkit/ch_xmlwrapp/figure/ch_xmlwrapp.1.2/?report=objectonly": ["i3", "/books/n/toolkit/ch_xmlwrapp", "", "ch_xmlwrapp", "", "/toolkit/doc/book/ch_xmlwrapp/?report=objectonly#ch_xmlwrapp.1.2", "", "/toolkit/doc/book/ch_xmlwrapp/?report=objectonly#ch_xmlwrapp.1.2"],
                "/books/NBK7184/figure/ch_intro.F1/?report=objectonly": ["i4", "/books/NBK7184", "", "ch_intro", "", "/toolkit/doc/book/ch_intro/?report=objectonly#ch_intro.F1", "", "/toolkit/doc/book/ch_intro/?report=objectonly#ch_intro.F1"],
                "/books/NBK7146/figure/ch_app.specs_asn/?report=objectonly": ["i5", "/books/NBK7146", "", "ch_app", "", "/toolkit/doc/book/ch_app/?report=objectonly#ch_app.specs_asn", "", "/toolkit/doc/book/ch_app/?report=objectonly#ch_app.specs_asn"],
                "/books/NBK8829/figure/ch_xmlwrapp.1.2/?report=objectonly": ["i6", "/books/NBK8829", "", "ch_xmlwrapp", "", "/toolkit/doc/book/ch_xmlwrapp/?report=objectonly#ch_xmlwrapp.1.2", "", "/toolkit/doc/book/ch_xmlwrapp/?report=objectonly#ch_xmlwrapp.1.2"],

                # floating tables
                "/books/n/toolkit/ch_demo/?rendertype=table&id=ch_demo.T5": ["j1", "/books/n/toolkit/ch_demo", "", "ch_demo", "", "/toolkit/doc/book/ch_demo/?rendertype=table#ch_demo.T5", "", "/toolkit/doc/book/ch_demo/?rendertype=table#ch_demo.T5"],
                "/books/n/toolkit/ch_libconfig/table/ch_libconfig.T8/?report=objectonly": ["j2", "/books/n/toolkit/ch_libconfig", "", "ch_libconfig", "", "/toolkit/doc/book/ch_libconfig/?report=objectonly#ch_libconfig.T8", "", "/toolkit/doc/book/ch_libconfig/?report=objectonly#ch_libconfig.T8"],
                "/books/n/toolkit/toolkit.fm/table/fm.T1/?report=objectonly": ["j3", "/books/n/toolkit/toolkit.fm", "", "toolkit.fm", "", "/toolkit/doc/book/toolkit.fm/?report=objectonly#fm.T1", "", "/toolkit/doc/book/toolkit.fm/?report=objectonly#fm.T1"],
                "/books/NBK7183/?rendertype=table&id=ch_demo.T5": ["j4", "/books/NBK7183", "", "ch_demo", "", "/toolkit/doc/book/ch_demo/?rendertype=table#ch_demo.T5", "", "/toolkit/doc/book/ch_demo/?rendertype=table#ch_demo.T5"],
                "/books/NBK7164/table/ch_libconfig.T8/?report=objectonly": ["j5", "/books/NBK7164", "", "ch_libconfig", "", "/toolkit/doc/book/ch_libconfig/?report=objectonly#ch_libconfig.T8", "", "/toolkit/doc/book/ch_libconfig/?report=objectonly#ch_libconfig.T8"],
                "/books/NBK22952/table/fm.T1/?report=objectonly": ["j6", "/books/NBK22952", "", "toolkit.fm", "", "/toolkit/doc/book/toolkit.fm/?report=objectonly#fm.T1", "", "/toolkit/doc/book/toolkit.fm/?report=objectonly#fm.T1"],

                # main pages
                "/books/n/toolkit/ch_intro": ["k1", "/books/n/toolkit/ch_intro", "", "ch_intro", "", "/toolkit/doc/book/ch_intro/", "", "/toolkit/doc/book/ch_intro/"],
                "/books/n/toolkit/part1": ["k2", "/books/n/toolkit/part1", "", "part1", "", "/toolkit/doc/book/part1/", "", "/toolkit/doc/book/part1/"],
                "/books/n/toolkit/part1?report=printable": ["k3", "/books/n/toolkit/part1", "", "part1", "", "/toolkit/doc/book/part1/?report=printable", "", "/toolkit/doc/book/part1/?report=printable"],
                "/books/n/toolkit/toolkit.fm": ["k4", "/books/n/toolkit/toolkit.fm", "", "toolkit.fm", "", "/toolkit/doc/book/toolkit.fm/", "", "/toolkit/doc/book/toolkit.fm/"],
                "/books/n/toolkit/app1.appendix1": ["k5", "/books/n/toolkit/app1.appendix1", "", "app1.appendix1", "", "/toolkit/doc/book/app1.appendix1/", "", "/toolkit/doc/book/app1.appendix1/"],
                "/books/NBK7184": ["k6", "/books/NBK7184", "", "ch_intro", "", "/toolkit/doc/book/ch_intro/", "", "/toolkit/doc/book/ch_intro/"],
                "/books/NBK7163": ["k7", "/books/NBK7163", "", "part1", "", "/toolkit/doc/book/part1/", "", "/toolkit/doc/book/part1/"],
                "/books/NBK7163?report=printable": ["k8", "/books/NBK7163", "", "part1", "", "/toolkit/doc/book/part1/?report=printable", "", "/toolkit/doc/book/part1/?report=printable"],
                "/books/NBK22952": ["k9", "/books/NBK22952", "", "toolkit.fm", "", "/toolkit/doc/book/toolkit.fm/", "", "/toolkit/doc/book/toolkit.fm/"],
                "/books/NBK7155": ["k10", "/books/NBK7155", "", "app1.appendix1", "", "/toolkit/doc/book/app1.appendix1/", "", "/toolkit/doc/book/app1.appendix1/"],

                # special table formatted content
                "/books/NBK7190/table/ch_conn.T.nc_conn_setcallbackconn_conn_e/?report=objectonly": ["l1", "/books/NBK7190", "", "ch_conn", "", "/toolkit/doc/book/ch_conn/?report=objectonly#ch_conn.T.nc_conn_setcallbackconn_conn_e", "", "/toolkit/doc/book/ch_conn/?report=objectonly#ch_conn.T.nc_conn_setcallbackconn_conn_e"],
                "/books/NBK7190/table/ch_conn.T.nc_conn_setcallbackconn_conn_e": ["l2", "/books/NBK7190", "", "ch_conn", "", "/toolkit/doc/book/ch_conn/#ch_conn.T.nc_conn_setcallbackconn_conn_e", "", "/toolkit/doc/book/ch_conn/#ch_conn.T.nc_conn_setcallbackconn_conn_e"],
                "/books/NBK7190#ch_conn.T.nc_conn_setcallbackconn_conn_e": ["l3", "/books/NBK7190", "", "ch_conn", "", "/toolkit/doc/book/ch_conn/", "", "/toolkit/doc/book/ch_conn/#ch_conn.T.nc_conn_setcallbackconn_conn_e"],

                # fragments
                "/books/n/toolkit/toolkit.fm#A2": ["m1", "/books/n/toolkit/toolkit.fm", "", "toolkit.fm", "", "/toolkit/doc/book/toolkit.fm/", "", "/toolkit/doc/book/toolkit.fm/#A2"],
                "/books/n/toolkit/toolkit.fm/#A2": ["m2", "/books/n/toolkit/toolkit.fm", "", "toolkit.fm", "", "/toolkit/doc/book/toolkit.fm/", "", "/toolkit/doc/book/toolkit.fm/#A2"],
                "/books/n/toolkit/ch_app/#ch_app.Load_Balancing": ["m3", "/books/n/toolkit/ch_app", "", "ch_app", "", "/toolkit/doc/book/ch_app/", "", "/toolkit/doc/book/ch_app/#ch_app.Load_Balancing"],
                "/books/n/toolkit/release_notes/#release_notes.Download": ["m4", "/books/n/toolkit/release_notes", "", "release_notes", "", "/toolkit/doc/book/release_notes/", "", "/toolkit/doc/book/release_notes/#release_notes.Download"],
                "/books/NBK22952#A2": ["m5", "/books/NBK22952", "", "toolkit.fm", "", "/toolkit/doc/book/toolkit.fm/", "", "/toolkit/doc/book/toolkit.fm/#A2"],
                "/books/NBK22952/#A2": ["m6", "/books/NBK22952", "", "toolkit.fm", "", "/toolkit/doc/book/toolkit.fm/", "", "/toolkit/doc/book/toolkit.fm/#A2"],
                "/books/NBK7146/#ch_app.Load_Balancing": ["m7", "/books/NBK7146", "", "ch_app", "", "/toolkit/doc/book/ch_app/", "", "/toolkit/doc/book/ch_app/#ch_app.Load_Balancing"],
                "/books/NBK7156/#release_notes.Download": ["m8", "/books/NBK7156", "", "release_notes", "", "/toolkit/doc/book/release_notes/", "", "/toolkit/doc/book/release_notes/#release_notes.Download"],

                # table footnotes
                "/books/n/toolkit/ch_libconfig/table/ch_libconfig.T8/?report=objectonly#__pp_ch_libconfig_TF_24": ["n1", "/books/n/toolkit/ch_libconfig", "", "ch_libconfig", "", "/toolkit/doc/book/ch_libconfig/?report=objectonly#ch_libconfig.T8", "", "/toolkit/doc/book/ch_libconfig/?report=objectonly#ch_libconfig.TF.24"],
                "/books/NBK7164/table/ch_libconfig.T8/?report=objectonly#__pp_ch_libconfig_TF_24": ["n2", "/books/NBK7164", "", "ch_libconfig", "", "/toolkit/doc/book/ch_libconfig/?report=objectonly#ch_libconfig.T8", "", "/toolkit/doc/book/ch_libconfig/?report=objectonly#ch_libconfig.TF.24"],

                # Copyright notice:
                "/books/n/toolkit/toc/#_ncbi_dlg_cpyrght_NBK7160": ["o1", "/books/n/toolkit/toc", "", "toc", "", "/toolkit/doc/book/", "", "/About/disclaimer.html"],
                "/books/NBK7160/#_ncbi_dlg_cpyrght_NBK7160": ["o2", "/books/NBK7160", "", "toc", "", "/toolkit/doc/book/", "", "/About/disclaimer.html"],
                "/books/NBK7160#_ncbi_dlg_cpyrght_NBK7160": ["o3", "/books/NBK7160", "", "toc", "", "/toolkit/doc/book/", "", "/About/disclaimer.html"],

                # Some very old URL formats:
                "/books/br.fcgi?asdf=qwer&book=toolkit&a=b&part=part1&x&&": ["p1", "part1", "", "part1", "", "/toolkit/doc/book/part1/", "", "/toolkit/doc/book/part1/"],
                "/books/br.fcgi?book=toolkit": ["p2", "toc", "", "toc", "", "/toolkit/doc/book/", "", "/toolkit/doc/book/"],
                "/books/br.fcgi?p1=v1&book=toolkit.section.ch_demo.id1_fetch.html&p2=v2": ["p3", "ch_demo", "", "ch_demo", "", "/toolkit/doc/book/ch_demo/#ch_demo.id1_fetch.html", "", "/toolkit/doc/book/ch_demo/#ch_demo.id1_fetch.html"],
                "/books/br.fcgi?part=ch_cgi&book=toolkit": ["p4", "ch_cgi", "", "ch_cgi", "", "/toolkit/doc/book/ch_cgi/", "", "/toolkit/doc/book/ch_cgi/"],
                #
                "/books/bv.fcgi?call=bv.View.ShowTOC&rid=toolkit": ["p11", "toc", "", "toc", "", "/toolkit/doc/book/", "", "/toolkit/doc/book/"],
                "/books/bv.fcgi?call=bv.View.ShowTOC&rid=toolkit.TOC&depth=2": ["p12", "toc", "", "toc", "", "/toolkit/doc/book/", "", "/toolkit/doc/book/"],
                "/books/bv.fcgi?call=bv.View..ShowTOC&rid=toolkit": ["p13", "toc", "", "toc", "", "/toolkit/doc/book/", "", "/toolkit/doc/book/"],
                "/books/bv.fcgi?call=bv.View..ShowTOC&rid=toolkit.TOC&depth=2": ["p14", "toc", "", "toc", "", "/toolkit/doc/book/", "", "/toolkit/doc/book/"],
                "/books/bv.fcgi?rid=toolkit": ["p15", "toc", "", "toc", "", "/toolkit/doc/book/", "", "/toolkit/doc/book/"],
                "/books/bv.fcgi?rid=toolkit&call=bv.View.ShowTOC": ["p16", "toc", "", "toc", "", "/toolkit/doc/book/", "", "/toolkit/doc/book/"],
                "/books/bv.fcgi?rid=toolkit&call=bv.View..ShowTOC": ["p17", "toc", "", "toc", "", "/toolkit/doc/book/", "", "/toolkit/doc/book/"],
                "/books/bv.fcgi?rid=toolkit.section.ch_demo.id1_fetch.html": ["p18", "ch_demo", "", "ch_demo", "", "/toolkit/doc/book/ch_demo/#ch_demo.id1_fetch.html", "", "/toolkit/doc/book/ch_demo/#ch_demo.id1_fetch.html"],
                "/books/bv.fcgi?rid=toolkit.TOC": ["p19", "toc", "", "toc", "", "/toolkit/doc/book/", "", "/toolkit/doc/book/"],
                "/books/bv.fcgi?rid=toolkit.TOC&call=bv.View.ShowTOC": ["p20", "toc", "", "toc", "", "/toolkit/doc/book/", "", "/toolkit/doc/book/"],
                "/books/bv.fcgi?rid=toolkit.TOC&call=bv.View..ShowTOC": ["p21", "toc", "", "toc", "", "/toolkit/doc/book/", "", "/toolkit/doc/book/"],
            }
            for testname in self.__tests.keys():
                testname_nofrag = testname.split("#")[0]
                testinfo = self.__tests[testname]
                if testinfo[1] == INVALID_INPUT:
                    testinfo[2] = INVALID_INPUT
                    testinfo[3] = INVALID_INPUT
                    testinfo[4] = INVALID_INPUT
                    testinfo[5] = INVALID_INPUT
                    testinfo[6] = INVALID_INPUT
                    testinfo[7] = INVALID_INPUT
                else:
                    try:
                        (testinfo[2], testinfo[4]) = Redirector.get_pages_in_out(testname_nofrag)
                        testinfo[6] = self.xform(testname_nofrag, False)
                    except Exception as ex:
                        testinfo[2] = str(ex)
                        testinfo[4] = str(ex)
                        testinfo[6] = str(ex)

        # Initialize HTML to empty string.
        self.__html = ""

    @staticmethod
    def get_pages_in_out(path_qry_in):
        "Find input and output pages for the given path."
        # Sample page patterns:
        # /books/NBK7160
        # /books/NBK7160/
        # /books/NBK7146?redirector_debug=1#ch_app.Load_Balancing
        # /books/n/toolkit/ch_app?redirector_debug=1#ch_app.Load_Balancing
        # /books/bv.fcgi?call=bv.View.ShowTOC&rid=toolkit.TOC&depth=2
        # /books/bv.fcgi?call=bv.View..ShowTOC&rid=toolkit.TOC&depth=2
        # /books/br.fcgi?book=toolkit
        transforms = [
            (r"\A(/books/NBK7160)/pdf/TOC\.pdf(?:[?#].*|)\Z", r"\1", r"toc"),
            (r"\A(/books/NBK7155)/pdf/app1\.pdf(?:[?#].*|)\Z", r"\1", r"app1.appendix1"),
            (r"\A(/books/)(NBK[0-9]+)/pdf/([^.]+)\.pdf(?:[?#].*|)\Z", r"\1\2", r"\3"),
            (r"\A(/books/)(NBK[0-9]+)(?:[/?#].*|)\Z", r"\1\2", r"\2"),
            (r"\A(/books/n/toolkit)/pdf/TOC\.pdf(?:[?#].*|)\Z", r"\1/toc", r"toc"),
            (r"\A(/books/n/toolkit)/pdf/app1\.pdf(?:[?#].*|)\Z", r"\1/app1.appendix1", r"app1.appendix1"),
            (r"\A(/books/n/toolkit)/toc/pdf/TOC\.pdf(?:[?#].*|)\Z", r"\1/toc", r"toc"),
            (r"\A(/books/n/toolkit)/([^/]+)/pdf/(\2\.pdf)(?:[?#].*|)\Z", r"\1/\2", r"\2"),
            (r"\A(/books/n/toolkit)/?([?#].*)?\Z", r"\1", r"toc"),
            (r"\A(/books/n/toolkit/)([^/?#]+)([/?#].*)?\Z", r"\1\2", r"\2"),
            (r"\A(/books/bv\.fcgi)[?](?!.*[?])(?:(?:(?<=[?])|&)(?:(rid=toolkit\.section\.([^.&#]+)(?:\.[^&#]*)?)|(?:[^&#]*)))+(?(2)|(?!))(#.*|)\Z", r"\3", r"\3"),
            (r"\A(/books/bv\.fcgi)[?](?!.*[?])(?:(?:(?<=[?])|&)(?:(rid=toolkit(?:\.TOC)?)|(part=)([^&#]+)|(?:[^&#]*))){2,}(?(2)|(?!))(?(3)|(?!))(#.*|)\Z", r"\4", r"\4"),
            (r"\A(/books/bv\.fcgi)[?](?!.*[?])(?:(?:(?<=[?])|&)(?:(rid=toolkit(?:\.TOC)?)|(?:[^&#]*)))+(?(2)|(?!))(#.*|)\Z", r"toc", r"toc"),
            (r"\A(/books/br\.fcgi)[?](?!.*[?])(?:(?:(?<=[?])|&)(?:(book=toolkit\.section\.([^.&#]+)(?:\.[^&#]*)?)|(?:[^&#]*)))+(?(2)|(?!))(#.*|)\Z", r"\3", r"\3"),
            (r"\A(/books/br\.fcgi)[?](?!.*[?])(?:(?:(?<=[?])|&)(?:(book=toolkit)|(part=)([^&#]+)|(?:[^&#]*))){2,}(?(2)|(?!))(?(3)|(?!))(#.*|)\Z", r"\4", r"\4"),
            (r"\A(/books/br\.fcgi)[?]([^&#]*&)*book=toolkit(\.[^&#]*)?([&#].*|)\Z", r"toc", r"toc"),
        ]

        # First see if you can parse a page from the known page patterns.
        page_in = ""
        page_out = ""
        for trans in transforms:
            if re.match(trans[0], path_qry_in):
                page_in = re.sub(trans[0], trans[1], path_qry_in)
                page_out = re.sub(trans[0], trans[2], path_qry_in)
                break
        if not page_in:
            raise RedirEx_PageNotFoundInUrl("The URL doesn't appear to contain a page.")

        # Now see if the parsed page matches a known page.
        acc2name = {
            "NBK7160": "toc",
            "NBK22952": "toolkit.fm",
            "NBK7155": "app1.appendix1",
            "NBK7163": "part1",
            "NBK7148": "part2",
            "NBK7201": "part3",
            "NBK7191": "part4",
            "NBK7196": "part5",
            "NBK7187": "part6",
            "NBK7192": "part7",
            "NBK8830": "part8",
            "NBK7184": "ch_intro",
            "NBK7194": "ch_start",
            "NBK7170": "ch_getcode_svn",
            "NBK7167": "ch_config",
            "NBK7157": "ch_build",
            "NBK7171": "ch_proj",
            "NBK7147": "ch_style",
            "NBK7185": "ch_core",
            "NBK7190": "ch_conn",
            "NBK7176": "ch_dbapi",
            "NBK7199": "ch_cgi",
            "NBK7166": "ch_html",
            "NBK7197": "ch_ser",
            "NBK7198": "ch_datamod",
            "NBK7169": "ch_objmgr",
            "NBK7152": "ch_blast",
            "NBK7179": "ch_dataaccess",
            "NBK7151": "ch_algoalign",
            "NBK7173": "ch_gui",
            "NBK7200": "ch_boost",
            "NBK8829": "ch_xmlwrapp",
            "NBK7158": "ch_debug",
            "NBK7188": "ch_grid",
            "NBK7146": "ch_app",
            "NBK7183": "ch_demo",
            "NBK7180": "ch_res",
            "NBK7182": "ch_browse",
            "NBK7161": "ch_devtools",
            "NBK7174": "ch_xmlauthor",
            "NBK7177": "ch_faq",
            "NBK7164": "ch_libconfig",
            "NBK7156": "release_notes",
            "NBK7165": "release_notes_03_09_2005",
            "NBK7175": "release_notes_03_12_2007",
            "NBK7162": "release_notes_04_30_2006",
            "NBK7186": "release_notes_05_05_2005",
            "NBK44965": "release_notes_05_15_2009",
            "NBK55594": "release_notes_06_29_2010",
            "NBK7154": "release_notes_08_01_2003",
            "NBK7153": "release_notes_08_14_2006",
            "NBK7193": "release_notes_08_27_2007",
            "NBK7178": "release_notes_10_03_2005",
            "NBK7172": "release_notes_10_2_2004",
            "NBK7149": "release_notes_11_22_2004",
            "NBK7159": "release_notes_12_08_2003",
            "NBK7189": "release_notes_12_24_2008",
            "NBK7150": "release_notes_12_31_2005",
            "NBK7168": "release_notes_12_31_2008",
            "NBK92948": "release_notes_7-05_2011",
            "NBK7181": "release_notes_7_8_2004",
            "NBK7195": "release_notes_april_16_2004",
            "NBK148849": "release_notes_v9_2012",
        }
        #
        if page_in == "/books/NBK22952" and page_out == "fm":
            return (page_in, "toolkit.fm")
        for acc in acc2name.keys():
            if page_out == acc and re.match(r"\A/books/NBK", page_in):
                page_out = acc2name[acc] # switch from accession-based to name-based page
                return (page_in, page_out)
            if re.match(acc2name[acc], page_out):
                return (page_in, page_out)
        raise RedirEx_ApparentInvalidPage("The URL appears to contain an invalid page.")

    @staticmethod
    def get_url_final_status(scheme, server, path, max_redirects=50, num_redirects=0):
        "Gets the HTTP status for a URL, following redirects."
        mat = re.match(r"\A(/.*)\Z", path)
        if mat:
            return Redirector.get_url_final_status_parts(scheme, server, mat.group(1), max_redirects, num_redirects)
        mat = re.match(r"\A(https?://)([^/?#]+)(.*)\Z", path)
        if mat and len(mat.groups()) == 3:
            return Redirector.get_url_final_status_parts(mat.group(1), mat.group(2), mat.group(3), max_redirects, num_redirects)
        return 500

    @staticmethod
    def get_url_final_status_parts(scheme, server, path, max_redirects=50, num_redirects=0):
        "Gets the HTTP status for a URL, following redirects."
        conn = httplib.HTTPConnection(server)
        conn.request("HEAD", path)
        resp = conn.getresponse()
        if resp.status >= 300 and resp.status < 400:
            if num_redirects < max_redirects:
                for hdr in resp.getheaders():
                    if hdr[0].lower() == "location":
                        return Redirector.get_url_final_status(scheme, server, hdr[1], max_redirects, num_redirects + 1)
        return resp.status

    @staticmethod
    def url_add_debug(url):
        "Add a debug query parameter to a URL."

        # First split the URL into path, query, and fragment parts.
        if "?" in url:
            (p, qf) = url.split("?")
            if "#" in qf:
                (q, f) = qf.split("#")
            else:
                q = qf
                f = ""
        else:
            q = ""
            if "#" in url:
                (p, f) = url.split("#")
            else:
                p = url
                f = ""

        # Now insert the debug query parameter.
        new_url = p
        if q:
            new_url += "?" + q + "&redirector_debug=1"
        else:
            new_url += "?redirector_debug=1"
        if f:
            new_url += "#" + f

        return new_url

    def xform(self, path_qry, save):
        "Transform the path/query string into a URL."

        def id():
            "Facilitate uniform access to monotonically increasing ID."
            Redirector.XFORM_ID += 1
            return Redirector.XFORM_ID

        # Get the input and output pages.
        (page_in, page_out) = Redirector.get_pages_in_out(path_qry)

        # Sample conversion:
        # click:        http://dev.ncbi.nlm.nih.gov/books/NBK7146?redirector_debug=1#ch_app.Load_Balancing
        #               http://dev.ncbi.nlm.nih.gov/books/n/toolkit/ch_app?redirector_debug=1#ch_app.Load_Balancing
        #
        # request:      http://dev.ncbi.nlm.nih.gov/books/NBK7146?redirector_debug=1
        #               http://dev.ncbi.nlm.nih.gov/books/n/toolkit/ch_app?redirector_debug=1
        #
        # PATH_INFO=/books/NBK7146
        # PATH_INFO=/books/n/toolkit/ch_app
        # QUERY_STRING=redirector_debug=1
        #
        # new_url:      http://dev.ncbi.nlm.nih.gov/toolkit/doc/book/ch_app?redirector_debug=1
        # final url:    http://dev.ncbi.nlm.nih.gov/toolkit/doc/book/ch_app?redirector_debug=1#ch_app.Load_Balancing

        # Path transformations, from redirected "extra path" to (almost) final URL:
        # (This is "almost" final because client-side JavaScript might rewrite it.)
        Redirector.XFORM_ID = -1
        transforms = [

            # Columns:
            # 0 -- transform index
            # 1 -- RT_AUTO if this page should be auto-redirected;
            #      RT_INFO to show an informational redirector page
            # 2 -- match pattern
            # 3 -- replacement text

            # PDFs
            (id(), Redirector.RT_INFO,  r"\A/books/n/toolkit/(?:toc/)?pdf/TOC\.pdf([?#].*|)\Z",
                                        r"/toolkit/doc/book/pdf/TOC.pdf\1"),
            (id(), Redirector.RT_INFO,  r"\A" + page_in + r"/pdf/TOC\.pdf([?#].*|)\Z",
                                        r"/toolkit/doc/book/pdf/TOC.pdf\1"),
            (id(), Redirector.RT_INFO,  r"\A" + page_in + r"/pdf/app1(?:\.appendix1)?\.pdf([?#].*|)\Z",
                                        r"/toolkit/doc/book/pdf/app1.pdf\1"),
            (id(), Redirector.RT_INFO,  r"\A" + page_in + r"/pdf/(?:toolkit\.)?fm\.pdf([?#].*|)\Z",
                                        r"/toolkit/doc/book/pdf/fm.pdf\1"),
            (id(), Redirector.RT_INFO,  r"\A" + page_in + r"/pdf/" + page_out + r"\.pdf([?#].*|)\Z",
                                        r"/toolkit/doc/book/pdf/" + page_out + r".pdf\1"),
            (id(), Redirector.RT_INFO,  r"\A" + page_in + r"/pdf/\Z",
                                        r"/toolkit/doc/book/pdf/app1.pdf\1"),

            # images
            (id(), Redirector.RT_INFO,  r"\A" + page_in + r"/bin/([^?#]+)([?#].*|)\Z",
                                        r"/toolkit/doc/book/img/\1\2"),

            # copyright notice
            (id(), Redirector.RT_INFO,  r"\A" + page_in + r"([^#]*)#_ncbi_dlg_cpyrght_NBK7160\Z",
                                        r"/About/disclaimer.html"),

            # floating items, e.g.
            # from:     /books/NBK22952/table/fm.T1/?report=objectonly
            # to:       /toolkit/doc/book/toolkit.fm/?report=objectonly#fm.T1
            # from:     /books/n/toolkit/ch_libconfig/table/ch_libconfig.T8/?report=objectonly
            # to:       /toolkit/doc/book/ch_libconfig/?report=objectonly#ch_libconfig.T8
            # from:     /books/NBK7183/?rendertype=table&id=ch_demo.T5
            # to:       /toolkit/doc/book/ch_demo/?rendertype=table#ch_demo.T5
            (id(), Redirector.RT_INFO,  r"\A" + page_in + r"/(?:box|figure|table)/fm\.([^/?#]+)/?([?][^#]*|)(?:#.*)?\Z",
                                        r"/toolkit/doc/book/toolkit.fm/\2#fm.\1"),
            (id(), Redirector.RT_INFO,  r"\A" + page_in + r"/(?:box|figure|table)/" + page_out + r"\.([^/?#]+)/?([?][^#]*|)(?:#.*)?\Z",
                                        r"/toolkit/doc/book/" + page_out + r"/\2#" + page_out + r".\1"),
            (id(), Redirector.RT_INFO,  r"\A" + page_in + r"/?([?]rendertype=(?:box|figure|table))&id=" + page_out + r"\.([^/&#]+)(?:.*)\Z",
                                        r"/toolkit/doc/book/" + page_out + r"/\1#" + page_out + r".\2"),

            # table footnotes, e.g.
            # from:     /books/n/toolkit/ch_libconfig/table/ch_libconfig.T8/?report=objectonly#__pp_ch_libconfig_TF_24
            # to:       /toolkit/doc/book/ch_libconfig/?report=objectonly#ch_libconfig.TF.24
            (id(), Redirector.RT_INFO,  r"\A" + page_in + r"/table/" + page_out + r"\.(?:[^/?#]+)/?([?]report=objectonly|)#__pp_" + page_out + r"_TF_([1-9][0-9]+)\Z",
                                        r"/toolkit/doc/book/" + page_out + r"/\1#" + page_out + r".TF.\2"),

            # old chapter formats
            (id(), Redirector.RT_INFO,  r"\A/books/br\.fcgi[?](?!.*[?])(?:(?:(?<=[?])|&)(?:(book=toolkit)|(part=" + page_out + r")|(?:[^&#]*))){2,}(?(1)|(?!))(?(2)|(?!))(#.*|)\Z",
                                        r"/toolkit/doc/book/" + page_out + r"/\3"),
            (id(), Redirector.RT_INFO,  r"\A/books/br\.fcgi[?](?!.*[?])(?:(?:(?<=[?])|&)(?:(book=toolkit\.section\." + page_out + r"(\.[^&#]*|))|(?:[^&#]*)))+(?(1)|(?!))(#.*|)\Z",
                                        r"/toolkit/doc/book/" + page_out + r"/#" + page_out + r"\2"),
            (id(), Redirector.RT_INFO,  r"\A/books/bv\.fcgi[?](?!.*[?])(?:(?:(?<=[?])|&)(?:(rid=toolkit\.section\." + page_out + r"(\.[^&#]*|))|(?:[^&#]*)))+(?(1)|(?!))(#.*|)\Z",
                                        r"/toolkit/doc/book/" + page_out + r"/#" + page_out + r"\2"),
            (id(), Redirector.RT_INFO,  r"\A/books/bv\.fcgi[?](?!.*[?])(?:(?:(?<=[?])|&)(?:(rid=toolkit(?:\.TOC)?)|(part=" + page_out + r")|(?:[^&#]*))){2,}(?(1)|(?!))(?(2)|(?!))(#.*|)\Z",
                                        r"/toolkit/doc/book/" + page_out + r"/\3"),

            # main page
            (id(), Redirector.RT_AUTO,  r"\A/books/n/toolkit/toc/?([?#].*|)\Z",
                                        r"/toolkit/doc/book/\1"),
            (id(), Redirector.RT_AUTO,  r"\A/books/(?:NBK7160|n/toolkit)/?([?#].*|)\Z",
                                        r"/toolkit/doc/book/\1"),
            (id(), Redirector.RT_AUTO,  r"\A/books/br\.fcgi[?](?!.*[?])(?:(?:(?<=[?])|&)(?:(book=toolkit)|(?:[^&#]*)))+(?(1)|(?!))(#.*|)\Z",
                                        r"/toolkit/doc/book/\2"),
            (id(), Redirector.RT_AUTO,  r"\A/books/bv\.fcgi[?](?!.*[?])(?:(?:(?<=[?])|&)(?:(rid=toolkit(?:\.TOC)?)|(?:[^&#]*)))+(?(1)|(?!))(#.*|)\Z",
                                        r"/toolkit/doc/book/\2"),

            # everything else
            (id(), Redirector.RT_INFO,  r"\A" + page_in + r"/?(.*)\Z",
                                        r"/toolkit/doc/book/" + page_out + r"/\1"),
        ]

        for trans in transforms:
            mat = re.match(trans[2], path_qry)
            if mat:
                self.resp_type = trans[1]
                res = re.sub(trans[2], trans[3], path_qry)
                if save:
                    self.__xform_idx = trans[0]
                    self.__xform_rt  = trans[1]
                    self.__xform_pat = trans[2]
                    self.__xform_rep = trans[3]
                    self.__xform_str = path_qry
                    self.__xform_groups = mat.groups()
                    self.__xform_res = res
                return res

        raise RedirEx_UnrecognizedUrlPattern("The URL doesn't match a recognized pattern.")

    def output_301(self):
        "Write redirect headers, with a brief new URL note per RFC2616."
        sys.stdout.write("Status: 301 Moved Permanently\n")
        sys.stdout.write("Location: %s\n" % self.__new_url_esc)
        sys.stdout.write("Content-type: text/plain\n")
        sys.stdout.write("\n")
        sys.stdout.write("The NCBI C++ Toolkit book has been moved to:\n")
        sys.stdout.write("http://www.ncbi.nlm.nih.gov/toolkit/doc/book/\n")

    def output_400(self):
        "Write bad request headers, with detailed supporting info."
        self.build_html()
        sys.stdout.write("Status: 400 Bad Request\n")
        sys.stdout.write("Content-type: text/html\n")
        sys.stdout.write("\n")
        sys.stdout.write(self.__html)

    def output_404(self):
        "Write not found headers, with detailed supporting info."
        self.build_html()
        sys.stdout.write("Status: 404 Not Found\n")
        sys.stdout.write("Content-type: text/html\n")
        sys.stdout.write("\n")
        sys.stdout.write(self.__html)

    @staticmethod
    def output_500(msg):
        "Write server error headers, with a brief explanatory message."
        sys.stdout.write("Status: 500 Internal Server Error\n")
        sys.stdout.write("\n")
        sys.stdout.write(msg + "\n")
        sys.exit(1)

    def build_html(self):
        "Build the entire HTML content prior to writing anything to STDOUT."
        self.__html = r"""<!DOCTYPE html PUBLIC "-//W3C//DTD XHTML 1.0 Transitional//EN" "http://www.w3.org/TR/xhtml1/DTD/xhtml1-transitional.dtd">
<html xmlns="http://www.w3.org/1999/xhtml" >
<head>
    <meta http-equiv="Content-Type" content="text/html; charset=utf-8" />
    <meta name="description" content="Redirects old NCBI-Bookshelf-based C++ Toolkit book URLs to new URLs." />
    <title>C++ Toolkit book - URL Redirector</title>"""

        # This section writes the server-side accessible URL info into a client-side
        # accessible location.
        self.__html += """

    <!--
        The following meta tags contain data that is only available on the server-side via CGI environment variables.
        However, the URL fragment is only available on the client-side (e.g. via JavaScript).
        Therefore, the old URL as shown here may be missing the originally requested fragment.
        Furthermore, the new URL could have a fragment appended - or it could even be completely
        rewritten if the client-side determines that that should happen based on both
        the server-side new_url and the client-side fragment.
    -->
    <meta id="meta_referer"     name="meta_referer"     content="%s" />
    <meta id="meta_old_url"     name="meta_old_url"     content="%s" />
    <meta id="meta_new_url"     name="meta_new_url"     content="%s" />""" % (
                self.__referer_esc,
                self.__old_url_esc,
                self.__new_url_esc,
            )

        if self.__debug_mode:
            self.__html += """
    <meta id="meta_scheme"      name="meta_scheme"      content="%s" />
    <meta id="meta_server_name" name="meta_server_name" content="%s" />""" % (
                self.__scheme,
                self.__server_name,
            )

            if self.resp_type == Redirector.RT_INFO or (self.method != "GET" and self.method != "HEAD"):
                self.__html += """
    <meta id="meta_resp_type"   name="meta_resp_type"   content="404 Not Found" />"""
            elif self.resp_type == Redirector.RT_AUTO:
                self.__html += """
    <meta id="meta_resp_type"   name="meta_resp_type"   content="301 Moved Permanently" />"""
            elif self.resp_type == Redirector.RT_BAD:
                self.__html += """
    <meta id="meta_resp_type"   name="meta_resp_type"   content="400 Bad Request" />"""
            else:
                self.__html += """
    <meta id="meta_resp_type"   name="meta_resp_type"   content="500 Server Error" />"""

        self.__html += """
    <link rel="stylesheet" type="text/css" href="redirector.css" />
</head>
<body>
    <table id="main-layout">
        <tr class="top-banner">
            <td class="top-banner">
                <table>
                    <tr>
                        <td class="logo-container">
                            <table>
                                <tr>
                                    <td>
                                        <a href="http://ncbi.nlm.nih.gov/"><img alt="NCBI logo" src="img/ncbi_logo_noborder.png" /></a>
                                    </td>
                                </tr>
                            </table>
                        </td>
                        <td>
                            <table>
                                <tr>
                                    <td id="banner-title">C++ Toolkit book - URL Redirector</td>
                                </tr>
                            </table>
                        </td>
                    </tr>
                </table>
            </td>
        </tr>
        <tr>
            <td>
                <table>
                    <tr>
                        <td id="main-content">
                            <div>
                                <h2>This isn't what I wanted - why did I get this page?</h2>"""

        if self.__debug_mode:
            if self.resp_type == Redirector.RT_INFO or (self.method != "GET" and self.method != "HEAD"):
                self.__html += """
                                <h2>404 Not Found</h2>"""
            elif self.resp_type == Redirector.RT_AUTO:
                self.__html += """
                                <h2>301 Moved Permanently</h2>"""
            elif self.resp_type == Redirector.RT_BAD:
                self.__html += """
                                <h2>400 Bad Request</h2>"""
            else:
                self.__html += """
                                <h2>500 Server Error</h2>"""

        txt_requested = "clicked a hyperlink, selected a bookmark, or otherwise requested"
        txt_therefore = "for a C++ Toolkit book page in the NCBI Bookshelf, which no longer hosts that book.  Therefore, you were redirected to this page which can help you get to the most similar content in the new C++ Toolkit book."
        if self.__referer_esc:
            if self.__old_url_given:
                self.__html += """
                                <h3 class="indent-1">It appears that:</h3>
                                <p class="indent-2">You were viewing this page:</p>
                                <p class="indent-3"><a class="url-1" href="%s">%s</a></p>""" % (self.__referer_esc, self.__referer_esc) + """
                                <p class="indent-2">You %s this URL:</p>""" % (txt_requested) + """
                                <p id="old_url" class="indent-3 url-1 url-old-book">%s</p>""" % (self.__old_url_esc) + """
                                <p class="indent-1">However, the requested URL is %s</p>""" % (txt_therefore)
            else:
                self.__html += """
                                <p class="indent-1">It appears that you were viewing the page shown below and %s a URL %s</p>""" % (txt_requested, txt_therefore) + """
                                <p class="indent-2"><a class="url-1" href="%s">%s</a></p>""" % (self.__referer_esc, self.__referer_esc)
        else:
            if self.__old_url_given:
                self.__html += """
                                <p class="indent-1">It appears that you %s the URL shown below. The URL is %s</p>""" % (txt_requested, txt_therefore) + """
                                <p id="old_url" class="indent-2 url-1 url-old-book">%s</p>""" % (self.__old_url_esc)
            else:
                self.__html += """
                                <p class="indent-1">It appears that you %s a URL %s</p>""" % (txt_requested, txt_therefore)

        # see RFC2616 comment in main()
        if self.resp_type == Redirector.RT_AUTO and self.method != "GET" and self.method != "HEAD":
            self.__html += """
                                <p class="indent-1">Note: Your request did not automatically forward because the request method was not GET or HEAD.</p>"""

        self.__html += """
                            </div>
                            <div>
                                <h2>How can I get to the page I wanted?</h2>
                                <div class="new_url_found_serverside%s">""" % ("" if self.__new_url_esc else " display-none") + """
                                    <p class="indent-1">Please try:</p>
                                    <p class="indent-1"><a id="new_url" class="url-2" href="%s">%s</a></p>""" % (self.__new_url_esc, self.__new_url_esc) + """
                                    <p class="indent-1"><span class="note-label">Note: </span>The above URL is the best approximation for the desired content in the new book and may not correspond exactly to the requested content in the old book.  For some URLs, the best approximation may not even be a valid URL.</p>
                                    <p class="indent-1">If that fails, please try searching for the desired content from the table of contents:</p>
                                    <p class="indent-1"><a class="url-2" href="%s">%s</a></p>""" % (self.__toc_loc_esc, self.__toc_loc_esc) + """
                                </div>
                                <div class="new_url_notfound_serverside%s">""" % (" display-none" if self.__new_url_esc else "") + """
                                    <p class="indent-1">The requested URL pattern was not recognized.  Therefore, please try searching for the desired content from the table of contents:</p>
                                    <p class="indent-1"><a class="url-2" href="%s">%s</a></p>""" % (self.__toc_loc_esc, self.__toc_loc_esc) + """
                                </div>
                                <noscript>
                                    <table class="indent-1">
                                        <tr>
                                            <td><img alt="No JavaScript warning" src="img/exclamation.png" class="icon" /></td>
                                            <td>
                                                <span class="note-label">Note: </span>JavaScript appears to be disabled in this browswer, which can cause the following problems:<br />
                                                <ul class="indent-1">
                                                    <li>Poor rendering and/or functionality in the C++ Toolkit book.</li>
                                                    <li>An incomplete or inaccurate translation of the requested old book URL into %s.</li>""" % ("the suggested new book URL above" if self.__new_url_esc else "a suggested new book URL") + """
                                                </ul>
                                                If you enable JavaScript and reload this page, it is possible that a %sURL will be suggested.""" % ("different " if self.__new_url_esc else "") + """
                                            </td>
                                        </tr>
                                    </table>
                                </noscript>
                            </div>
                            <div>
                                <h2>How can I avoid this page in the future?</h2>
                                <ul class="indent-1">
                                    <li>If you arrived here after selecting a bookmark, update it to the URL in the previous section.</li>
                                    <li>If you arrived here after clicking a link on a web page, please ask the maintainer of that page to update it.</li>
                                    <li>Bookmark the new location for the C++ Toolkit book:<br />
                                        <span class="indent-1 url-1"><a href="%s">%s</a></span>""" % (self.__toc_loc_esc, self.__toc_loc_esc) + """
                                    </li>
                                </ul>
                            </div>"""

        if self.__debug_mode:
            self.__html += """
                            <div class="separated-section">
                                <p class="main-sect-title">Debug Info</p>
                                <table class="vars-table">
                                    <tr>
                                        <th>Variable</th>
                                        <th>Value</th>
                                    </tr>
                                    <tr>
                                        <td>JavaScript enabled</td>
                                        <td><noscript>no</noscript><span id="debug_javascript"></span></td>
                                    </tr>
                                    <tr>
                                        <td>Browser Fragment</td>
                                        <td><noscript>(unknown)</noscript><span id="debug_fragment"></span></td>
                                    </tr>
                                    <tr>
                                        <td>Xform Input String</td>
                                        <td>%s</td>""" % (cgi.escape(self.__xform_str)) + """
                                    </tr>
                                    <tr>
                                        <td>Xform Index</td>
                                        <td>%s</td>""" % (self.__xform_idx) + """
                                    </tr>
                                    <tr>
                                        <td>Xform Response Type</td>
                                        <td>%s</td>""" % (self.__xform_rt) + """
                                    </tr>
                                    <tr>
                                        <td>Xform Pattern</td>
                                        <td>%s</td>""" % (cgi.escape(self.__xform_pat)) + """
                                    </tr>
                                    <tr>
                                        <td>Xform Replacement</td>
                                        <td>%s</td>""" % (cgi.escape(self.__xform_rep)) + """
                                    </tr>"""
            if self.__xform_groups is not None and len(self.__xform_groups) > 0:
                for grp_idx, grp_val in enumerate(self.__xform_groups):
                    self.__html += """
                                    <tr>
                                        <td>Xform Group %s</td>""" % (grp_idx + 1) + """
                                        <td>%s</td>""" % (cgi.escape(repr(grp_val))) + """
                                    </tr>"""
            self.__html += """
                                    <tr>
                                        <td>Xform Result</td>
                                        <td>%s</td>""" % (cgi.escape(self.__xform_res)) + """
                                    </tr>"""
            self.__html += """
                                </table>
                            </div>
                            <div class="separated-section">
                                <p class="main-sect-title">Test Transformations</p>
                                <table class="vars-table">
                                    <tr>
                                        <th>ID</th>
                                        <!--
                                        <th>R</th>
                                        <th>C</th>
                                        -->
                                        <th>Alias</th>
                                        <th>Client Input URL without debug (with debug) /<br />Server Input URL without debug (with debug)</th>
                                        <th>Expected Page In /<br />Transformed Page In</th>
                                        <th>Expected Page Out /<br />Transformed Page Out</th>
                                        <th>Expected Server URL /<br />Transformed Server URL</th>
                                        <th>Expected Client URL /<br />Transformed Client URL</th>
                                    </tr>"""

            for idx, client_url_in in enumerate(sorted(self.__tests.keys())):

                test_alias   = self.__tests[client_url_in][0]
                page_in_exp  = self.__tests[client_url_in][1]
                page_in_got  = self.__tests[client_url_in][2]
                page_out_exp = self.__tests[client_url_in][3]
                page_out_got = self.__tests[client_url_in][4]
                url_exp      = self.__tests[client_url_in][5]
                url_got      = self.__tests[client_url_in][6]
                client_url_exp  = self.__tests[client_url_in][7]

                client_debug        = Redirector.url_add_debug(client_url_in)
                server_url_in       = client_url_in.split("#")[0]
                esc_client_url_in   = cgi.escape(client_url_in)
                esc_client_debug    = cgi.escape(client_debug)
                esc_server_url_in   = cgi.escape(server_url_in)
                esc_server_url_exp  = cgi.escape(url_exp)
                esc_server_url_got  = cgi.escape(url_got)
                esc_client_url_exp  = cgi.escape(client_url_exp)

                id_str = str(idx + 1)

                link_client_url_in  = """<a id="url_in_%s" href="%s://%s%s">%s</a>""" % (id_str, self.__scheme, self.__server_name, esc_client_url_in, esc_client_url_in)
                link_client_debug   = """<a href="%s://%s%s">(with debug)</a>""" % (self.__scheme, self.__server_name, esc_client_debug)
                link_server_url_in  = """<a href="%s://%s%s">%s</a>""" % (self.__scheme, self.__server_name, esc_server_url_in, esc_server_url_in)
                link_server_debug   = """<a href="%s://%s%s">(with debug)</a>""" % (self.__scheme, self.__server_name, cgi.escape(Redirector.url_add_debug(server_url_in)))
                link_server_url_exp = """<a href="%s://%s%s">%s</a>""" % (self.__scheme, self.__server_name, esc_server_url_exp, esc_server_url_exp)
                link_server_url_got = """<a id="url_trans_%s" href="%s://%s%s">%s</a>""" % (id_str, self.__scheme, self.__server_name, esc_server_url_got, esc_server_url_got)
                link_client_url_exp = """<a id="url_out_exp_%s" href="%s://%s%s">%s</a>""" % (id_str, self.__scheme, self.__server_name, esc_client_url_exp, esc_client_url_exp)

                class_str_invalid = " class=\"invalid-input\""
                class_str_pass    = " class=\"test-pass\""
                class_str_fail    = " class=\"test-fail\""

                test_id_str = "" if page_in_exp == INVALID_INPUT else " class=\"test-id\""

                class_str_1 = class_str_invalid if page_in_exp == INVALID_INPUT else ""
                input_str = "<span%s>%s</span> %s<br /><span%s>%s</span> %s" % (class_str_1, link_client_url_in, link_client_debug, class_str_1, link_server_url_in, link_server_debug)

                class_str_1 = class_str_invalid if page_in_exp == INVALID_INPUT else ""
                if page_in_exp == INVALID_INPUT and page_in_got == INVALID_INPUT:
                    class_str_2 = class_str_1
                else:
                    class_str_2 = class_str_pass if page_in_exp == page_in_got else class_str_fail
                page_in_str = "<span%s>%s</span><br /><span%s>%s</span>" % (class_str_1, cgi.escape(page_in_exp), class_str_2, cgi.escape(page_in_got))

                class_str_1 = class_str_invalid if page_out_exp == INVALID_INPUT else ""
                if page_out_exp == INVALID_INPUT and page_out_got == INVALID_INPUT:
                    class_str_2 = class_str_1
                else:
                    class_str_2 = class_str_pass if page_out_exp == page_out_got else class_str_fail
                page_out_str = "<span%s>%s</span><br /><span%s>%s</span>" % (class_str_1, cgi.escape(page_out_exp), class_str_2, cgi.escape(page_out_got))

                class_str_1 = class_str_invalid if url_exp == INVALID_INPUT else ""
                str_1 = INVALID_INPUT if url_exp == INVALID_INPUT else link_server_url_exp
                str_2 = INVALID_INPUT if url_got == INVALID_INPUT else link_server_url_got
                if url_exp == INVALID_INPUT:
                    class_str_2 = class_str_invalid if url_got == INVALID_INPUT else class_str_fail
                else:
                    class_str_2 = class_str_pass if url_exp == url_got else class_str_fail
                out_server_str = "<span%s>%s</span><br /><span%s>%s</span>" % (class_str_1, str_1, class_str_2, str_2)

                class_str_1 = class_str_invalid if url_exp == INVALID_INPUT else ""
                str_1 = INVALID_INPUT if url_exp == INVALID_INPUT else link_client_url_exp
                str_2 = INVALID_INPUT if url_exp == INVALID_INPUT else "(undetermined)"
                out_client_str = """<span id="client_url_exp_%s"%s>%s</span><br /><span id="client_url_got_%s"%s>%s</span>""" % (id_str, class_str_1, str_1, id_str, class_str_invalid, str_2)

                self.__html += """
                                    <tr>
                                        <td%s>%s</td>""" % (test_id_str, id_str) + """
                                        <!--
                                        <td><input type="checkbox" /></td>
                                        <td><input type="checkbox" /></td>
                                        -->
                                        <td>%s</td>""" % (test_alias) + """
                                        <td>%s</td>""" % (input_str) + """
                                        <td>%s</td>""" % (page_in_str) + """
                                        <td>%s</td>""" % (page_out_str) + """
                                        <td>%s</td>""" % (out_server_str) + """
                                        <td>%s</td>""" % (out_client_str) + """
                                    </tr>"""

            self.__html += """
                                </table>
                            </div>
                            <div class="separated-section">
                                <p class="main-sect-title">Environment Variables</p>
                                <table class="vars-table">
                                    <tr>
                                        <th>Variable</th>
                                        <th>Value</th>
                                    </tr>"""

            for var in sorted(os.environ.keys()):
                self.__html += """
                                    <tr>
                                        <td>%s</td>
                                        <td>%s</td>
                                    </tr>""" % (
                    var,
                    "(see HTML comment)<!--" + cgi.escape(os.environ[var]) + "-->" if var == "HTTP_COOKIE" else
                    cgi.escape(os.environ[var]))

            self.__html += """
                                </table>
                            </div>"""

        self.__html += """
                        </td>
                    </tr>
                    <tr class="bottom-banner">
                        <td>
                            <table>
                                <tr>
                                    <td>
                                        <ul class="hor-navlist">
                                            <li class="hor-navlist-first"><a href="http://www.nih.gov/">NIH</a></li>
                                            <li><a href="http://www.nlm.nih.gov/">NML</a></li>
                                            <li><a href="http://ncbi.nlm.nih.gov/">NCBI</a></li>
                                            <li><a href="mailto:info@ncbi.nlm.nih.gov">Help</a></li>
                                        </ul>
                                    </td>
                                </tr>
                            </table>
                        </td>
                    </tr>
                </table>
            </td>
        </tr>
    </table>
    <script type="text/javascript" src="redirector.js"></script>"""

        if self.__debug_mode:
            self.__html += """
    <script type="text/javascript" src="redirector_debug.js"></script>"""

        self.__html += """
</body>
</html>
"""


def main():
    "The main functionality when directly invoked."
    try:
        redir = Redirector()
        # Per RFC2616, the user agent shouldn't auto-redirect if the request method is not GET or HEAD.
        # However, user agents don't always follow this rule.  Therefore, to compensate, this script will simply not return a 3xx code in this case.
        if redir.resp_type == Redirector.RT_INFO or (redir.method != "GET" and redir.method != "HEAD"):
            redir.output_404()
        elif redir.resp_type == Redirector.RT_AUTO:
            redir.output_301()
        elif redir.resp_type == Redirector.RT_BAD:
            redir.output_400()
        else:
            Redirector.output_500(
                """Invalid response type: "%s".""" % repr(redir.resp_type))
    except RedirEx as ex:
        Redirector.output_500("""Redirection exception: "%s".""" % ex)
    except Exception as ex:
        Redirector.output_500("""General exception: "%s".""" % ex)
    except:
        Redirector.output_500("Unknown exception.")

if __name__ == "__main__":
    main()
    sys.exit(0)
