// Generated by CoffeeScript 1.9.1
(function() {
  var getPathToRoot, test,
    extend = function(child, parent) { for (var key in parent) { if (hasProp.call(parent, key)) child[key] = parent[key]; } function ctor() { this.constructor = child; } ctor.prototype = parent.prototype; child.prototype = new ctor(); child.__super__ = parent.prototype; return child; },
    hasProp = {}.hasOwnProperty;

  module.exports = function(BasePlugin) {
    var PathToRoot;
    return PathToRoot = (function(superClass) {
      extend(PathToRoot, superClass);

      function PathToRoot() {
        return PathToRoot.__super__.constructor.apply(this, arguments);
      }

      PathToRoot.prototype.name = 'pathtoroot';

      PathToRoot.prototype.renderBefore = function(opts, next) {
        var docpad, documents;
        docpad = this.docpad;
        docpad.log('debug', 'Creating paths to root');
        opts.templateData.relativeToRoot = function(path) {
          return this.document.pathToRoot + path;
        };
        documents = docpad.getCollection('documents');
        documents.forEach(function(document) {
          var documentUrl, pathToRoot;
          documentUrl = document.get('url');
          pathToRoot = getPathToRoot(documentUrl);
          return document.set('pathToRoot', pathToRoot);
        });
        return next();
      };

      return PathToRoot;

    })(BasePlugin);
  };

  getPathToRoot = function(absolute_url) {
    var depth, i, j, pathToRoot, ref;
    depth = absolute_url.split('/').length - 1;
    if (depth === 1) {
      return '.';
    }
    pathToRoot = [];
    for (i = j = 0, ref = depth - 2; 0 <= ref ? j <= ref : j >= ref; i = 0 <= ref ? ++j : --j) {
      pathToRoot.push('..');
    }
    return pathToRoot.join('/');
  };

  test = function() {
    var assert;
    assert = require('assert');
    assert.equal(getPathToRoot('/'), '.');
    assert.equal(getPathToRoot('/aa.html'), '.');
    assert.equal(getPathToRoot('/aa/bb.html'), '..');
    assert.equal(getPathToRoot('/aa/bb/cc.html'), '../..');
    assert.equal(getPathToRoot('/aa/bb/dd/cc.html'), '../../..');
    return console.log('tests complete');
  };

  module.exports.test = test;

}).call(this);
