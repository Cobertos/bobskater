# Contributing

The library is broken up into two parts:

1. The `FrameTrackingNodeVisitor` extends `ast.NodeVisitor`. By passing it the AST for a file, it will process the entire thing and return scoping information for all identifiers found. These are processed as `FrameTrackingNodeVisitor.Frame` and `FrameTrackingNodeVisitor.FrameEntry`. Public methods then allow querying of this internal representation (TODO: this representation shouldn't be internal to the walker but should output it so user's can query it instead of public methods).

2. The `ReleaseObfuscationTransformer`. This transforms the given AST into the obfuscated AST. It will internally use `FrameTrackingNodeVisitor` to get the scoping information for a file to determine how to obfuscate it.

## Commands

#### Testing:
`pytest` - Runs all the tests

#### Releasing:
Refer to [the python docs on packaging for clarification](https://packaging.python.org/tutorials/packaging-projects/).
Make sure you've updated `setup.py`, and have installed `twine`, `setuptools`, and `wheel`
`python3 setup.py sdist bdist_wheel` - Create a source distribution and a binary wheel distribution into `dist/`
`twine upload dist/bobskater-x.x.x*` - Upload all `dist/` files to PyPI of a given version