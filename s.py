"""
This is a sketch of a new sort of webserver.

This new sort of webserver would make "normal" things easier.
"normal" things are the kind of things you do with Apache: serving
files, setting up nice indexing, filtering with xslt (or other
things), serving files or small one off urls easily.


Here's an example of what the config/bootstrap of such a server might
look like:

  from somemodule import admin_callable, summary_callable
  from os.path import join as joinpath

  server = Server(port=8000)                    # starts a webserver on port 8000     
  server.docroot = "/home/woome/ci"             # set the docroot for this namespace  
  server.directory["/"].index.auto = True       # make an auto index on the directory 
  server.directory["/"].index.header.virtual = "/summary"  # include the url /summary in the index
  server.url["/summary/$"] = summary_callable   # Define how the summary is generated
  server.url["/summary/$"].filter.xslt.filename = "transforms/summary.xslt" # Filter the summary with an XSLT
  admin = server.namespace["/admin/$"]          # makes a namespace for more config   
  admin.url["/user/$"] = list_users             # Define an admin handler
  admin.url["/user/(?P<username>[A-Za-z]+)/$"] = show_user # Define a user admin handler

That is designed to be written by a user. Obviously, the above is a
relatively complex config for this kind of use case.


== Namespaces ==

Namespaces are obviously url spaces declared with a prefix. These seem
relatively difficult to implement so I may not do these for now.

== Docroot ==

If a docroot is defined then the server automatically serves files
from the filesystem. This is what I was aiming for, something as easy
to get going with as apache, but a bit more flexible and with less mad
syntax.

However, docroot and file serving as a special case does irk me. Why
is it not possible to do auto-indexing across all sorts of different
collection types? Maybe we could define collection types (filesystems,
sql results, json values, etc...) On the other hand, filesystem
serving is pretty obvious and common.

== Filters ==

The reason for doing this server is so I have the opportunity to make
a lot of things better than they are with apache. One of the key areas
I want to achieve this is with filters.

Apache has mod_xslt and other things but it's complex and
constrained. I would like to make it easy to filter things like xml
and json and return html from the server side. Especially json. I like
the idea, for example, of returning the auto directory lists as
json. If a filter can be added to the directory to filter the json
into html we have a really powerful medium.

If that can be made to work well then virtual directorys might be
possible where you make a driver to deliver data for a namespace from
some source (eg: a database).

Then it will be really easy to make very RESTfull services very
quickly.

== More missing things ==

Any idea about what the API for callables is like is missing. Maybe it
would just be CGI, maybe it would be something else python standardy
like webob.
"""

from os.path import join as joinpath
from os.path import abspath
import re

class HttpError(Exception):
    pass

class Http404(HttpError):
    pass

class Header(object):
    def __init__(self):
        self.virtual = ""
        self.file = ""

class Index(object):
    def __init__(self, directory):
        self.directory = directory
        self.auto = False
        self.filename = None
        self.header = None

    def __setattr__(self, k, v):
        if k == "filename":
            self.__dict__.update({
                    "filename": v,
                    "auto": False,
                    "header": None
                    })
        if k == "auto":
            self.__dict__.update({
                    "filename": None,
                    "auto": True,
                    "header": Header()
                    })

    def __render__(self):
        if self.filename:
            try:
                with open(joinpath(self.directory, self.filename)) as fd:
                    return fd.read()
            except:
                raise Http404()

class Directory(object):
    """Represent a specific directory"""
    def __init__(self, dirname):
        self.dirname = dirname
        self.index = Index(self)

    def __str__(self):
        return self.dirname

class ItemContainer(object):
    """Generally contain items of a specific class. Create them on the fly"""
    def __init__(self, cls):
        self.items = {}
        self.object = cls

    def __getitem__(self, n):
        try:
            return self.items[n]
        except KeyError:
            self.items[n] = self.object(n)
            return self.items[n]

class Namespace(object):
    def __init__(self):
        self.urls = {}

    def __setitem__(self, path_re, proc):
        if path_re[0] != "^":
            path_re = "^" + path_re
        self.urls[re.compile("^" + path_re)] = proc

    def __match__(self, path):
        if path[-1] != "/":
            return self.__match__(path + "/")
        for pathre, proc in self.urls.iteritems():
            m = pathre.match(path)
            if m:
                return m, proc
        raise Http404(path)

from pyproxyfs import Filesystem

class Server(object):
    """A comprehensive webserver.

    Some special attributes are supported:

     'docroot'
     sets the server to serve files from the specified location

     'directory' 
     a dict like object which let's you specify properties for
     specific directories. this automatically comes into being
     when docroot is set.
    """
    def __init__(self, **kwargs):
        for k,v in kwargs:
            self.__dict__[k] = v
        self.__dict__["fs"] = Filesystem()
        self.__dict__["url"] = Namespace()
        # not sure about this
        # ... namespace is just a prefix? maybe just take it out and do it later
        self.__dict__["namespace"] = ItemContainer(Namespace) 

    def __getattr__(self, n):
        return self.__dict__[n]

    def __setattr__(self, n, v):
        """Set items on the server. See class doc for reference."""
        if n == "docroot":
            self.__dict__["docroot"] = abspath(v)
            self.__dict__["directory"] = ItemContainer(Directory)
        else:
            # We should really protect directory from being set directly
            # (and url, and namespace)
            self.__dict__[n] = v

    def __dispatch__(self, path=None):
        """Internal dispatch to defined handler"""
        try:
            match, handler = self.__dict__["url"].__match__(path)
            if match.groups():
                return handler(**match.groupdict())
            else:
                return handler()
        except Http404, e:
            # Dispatch to fileserver if we have it
            return self._handle(path)

    def _handle(self, path):
        """file server handler"""

        fs = self.__dict__["fs"]
        docroot = self.__dict__["docroot"]
        p = joinpath(docroot, path.strip("/"))

        # Do an abspath check on the requested path
        ap = abspath(p)
        try:
            assert(ap.index(docroot) == 0)
        except (ValueError, AssertionError):
            # THE PATH IS TRYING TO ESCAPE DOCROOT
            # I am not sure that 404 is correct... but what should it be?
            raise Http404(path)

        if not fs.exists(ap):
            raise Http404(path)

        # Handle the serving of files
        if fs.isdir(ap):
            server_part = ap.split(docroot)[1] or "/"
            if self.directory[server_part].index.auto:
                entries = [entry for entry in fs.listdir(ap)]
                html = "<br/>\n".join(["""<a href="%s">%s</a>""" % (
                            entry,
                            entry
                            ) for entry in entries])
                return "<html><body>%s</body></html>" % html
            if self.directory[server_part].index.filename:
                with fs.open(joinpath(
                        ap, 
                        self.directory[server_part].index.filename
                        )) as fd:
                    return fd.read()

            # Directory doesn't have a filename
            return fs.listdir(ap)
        else:
            with fs.open(ap) as fd:
                return fd.read()

    def __wsgi__(self):
        """Return a wsgi handler for this server"""
        def wsgidispatch(environ, start_response):
            try:
                response = self.__dispatch__(path=environ["PATH_INFO"])
            except Exception, e:
                print e
                start_response('500 Error', [('content-type', 'text/html')])
                return ["<p>BAH! %s</p>" % e]
            else:
                start_response('200 Ok', [('content-type', 'text/html')])
                return response
        return wsgidispatch


from unittest import TestCase
class Test(TestCase):
    """Simple tests"""

    def test_dir_config(self):
        """
        Test the configuration system.

        Sets up a server and configures various things on it making
        assertions that everything is configured correctly.
        """
        s = Server()
        s.docroot = '/home/woome/ci'
        self.assert_(s.directory["/test_results"].index.auto == False)
        self.assert_(
            s.directory["/test_results"].index.filename == None,
            "index filename = %s" % s.directory["/test_results"].index.filename
            )
        
        s.directory["/test_results"].index.filename = "index.html"
        self.assert_(s.directory["/test_results"].index.filename == "index.html")

        self.assert_(s.directory["/test_results"].index.auto == False)
        s.directory["/test_results"].index.auto = True
        self.assert_(s.directory["/test_results"].index.header.virtual == "")
        s.directory["/test_results"].index.header.virtual = "/summary"
        self.assert_(s.directory["/test_results"].index.header.virtual == '/summary')

        s.directory["/test_results"].index.filename = "index.html"
        self.assertRaises(
            Http404, 
            lambda: s.directory["/test_results"].index.__render__()
            )

    def test_url_dispatch(self):
        """
        Test the url dispatch logic of Server.
        """
        def plain_handler():
            return "OK"

        def regex_handler(name):
            return name

        s = Server()
        s.url["/one/$"] = plain_handler
        s.url["/two/(?P<name>[A-Za-z]+)/$"] = regex_handler

        self.assert_(
            s.__dispatch__(path="/one") == "OK",
            "dispatch of /one = %s" % s.__dispatch__(path="/one")
            )

        self.assert_(s.__dispatch__(path="/two/Nic") == "Nic")
        self.assert_(s.__dispatch__(path="/two/Nic/") == "Nic")

    def test_fileserver(self):
        """
        Test the built in fileserver.
        """
        s = Server()
        from pyproxyfs import TestFS
        testfs = TestFS({
                "home/woome/ci/test_results/20100730/file.txt": "result 1",
                "home/woome/ci/test_results/index.html": "the index",
                })
        s.__dict__["fs"] = testfs
        s.docroot = "/home/woome/ci"

        self.assertRaises(
            Http404,
            lambda: s.__dispatch__(path="/../../../test_results/")
            )

        testresults_dir = s.__dispatch__(path="/test_results/")
        self.assert_(
            testresults_dir == ['index.html', '20100730'],
            "the result from /test_results/ was: %s" % testresults_dir
            )

        s.directory["/test_results"].index.auto = True
        expected = """<html><body><a href="index.html">index.html</a><br/>
<a href="20100730">20100730</a></body></html>"""
        got = s.__dispatch__(path="/test_results/")
        self.assert_(
            got == expected,
            "instead of expected, got: %s" % got
            )

        s.directory["/test_results"].index.filename = "index.html"
        self.assert_(s.__dispatch__(path="/test_results/") == "the index")

        self.assert_(s.__dispatch__(path="/test_results/20100730") == ['file.txt'])
        self.assert_(s.__dispatch__(path="/test_results/20100730/file.txt") == 'result 1')


### Spawning stuff 
### Start this under spawning like:
###    spawn -p 8110 -f s.spawning_config_factory none
### this interface needs significant work

def app_factory(conf):
    s = Server()
    s.docroot = "/home/nferrier/woome/newserver/docroot"
    s.directory["/"].index.auto = True
    s.directory["/"].index.filename = "index.html"
    return s.__wsgi__()

def spawning_config_factory(args):
    """A Spawning config factory"""
    return {
        'args': args,
        'host': args.get('host'),
        'port': args.get('port'),
        'app_factory': "s.app_factory",
        'app': "", 
        'num_processes': 1,
        }

if __name__ == "__main__":
    from unittest import main
    main()
                     
# End
