# bobskater

An AST based Python obfuscator that robustly mangles names and other obfuscations of Python code

### Current limitations:
* DOES NOT SUPPORT: Annotations, evals, templated strings, imports of the form import xxx.yyy
* Very little configuration currently and instead takes a cautious approach in determining what identifiers to mangle. Globals, kwargs, class namespace identifiers, and others are not obfuscated but type of obfuscations should be use selected in the future.
* It is only tested with Python v3.5 and might not work with other AST versions
* Scoping for comprehensions are kind of hacky (and basically follows Python 2 comprehension scope leaking methodology)

### Installation

```
pip install bobskater
```

### Usage

`bobskater` provides a few mechanisms for direct use.

* `obfuscateString("")` obfuscates a string of source code.
* `obfuscateFile('myfile.py')` will obfuscate an entire file and overwrite the original

Both take keyword arguments for configuration:

* `removeDocstrings` will remove docstrings by replacing them with `pass` statements (to handle even cases where a function has only a docstring). Defaults to `True`
* `obfuscateNames` will obfuscate all names except globally scoped variables, kwargs, builtins, and identifiers in a class namespace. Defaults to `True`

There are no other obfuscations performed than the two mentioned above currently in `bobskater`

#### Example

```
from bobskater import obfuscateString

myFileContents = open('myfile.py', 'r').read()

#Will obfuscate myFileContents and return it into output. Names will not be mangled, only docstrings will be removed
output = obfuscateString(myFileContents, obfuscateNames=False)
```

### Contributing

##### Testing:
`pytest` - Runs all the tests

##### Releasing:
Refer to [the python docs on packaging for clarification](https://packaging.python.org/tutorials/packaging-projects/).
Make sure you've updated `setup.py`, and have installed `twine`, `setuptools`, and `wheel`
`python3 setup.py sdist bdist_wheel` - Create a source distribution and a binary wheel distribution into `dist/`
`twine upload dist/bobskater-x.x.x*` - Upload all `dist/` files to PyPI of a given version
Make sure to tag the commit you released