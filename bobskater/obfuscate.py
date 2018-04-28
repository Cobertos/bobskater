"""
Obfuscate a python file so it still works

Has issues:
Doesn't support any sort of annotations (skips them, should be okay for now?)
Hacky patch of comprehensions (see top, reverses for one specific thing so the _fields prints out the right way due to)
Comprehesions do not push a stack and basically use Python 2 behavior where their identifiers leak
Eval, strings, and other oddities are unconsidered for identifiers. Attributes are unconsidered too
kwargs need to NOT be mangled (as they are referenced at the call site)
"""
import builtins #Do not use __builtins__, it's different in different implementations (like IPython vs CPython)
import keyword
import sys
import ast
import string
import unicodedata
import itertools
from collections import defaultdict, namedtuple
import astunparse

logLevel = 0

def iter_fields_patch(node):
    """
    patch of ast.py iter_fields so that ast.ListComp, ast.SetComp, etc are iterated in reverse so that
    the for clause comes before the expression evaluated by the for clause (we might be able to take
    this out now that theirs the 2 stage approach but unconfirmed)
    """
    it = node._fields if not isinstance(node, (ast.ListComp, ast.SetComp, ast.GeneratorExp, ast.DictComp)) else \
        reversed(node._fields)
    for field in it:
        try:
            yield field, getattr(node, field)
        except AttributeError:
            pass
ast.iter_fields = iter_fields_patch

def validIdentifierIterator(version=2):
    """
    Compute strings of the valid identifier characters (for Python2, including start
    and "tail" characters after the first one)
    """
    #Determine characters we can use
    if version == 2:
        validIDStart = string.ascii_letters + "_"
        validID = string.ascii_letters + "_" + string.digits
    else:
        #Version 3
        #Get all unicode categories
        unicode_category = defaultdict(str)
        for c in map(chr, range(min(sys.maxunicode + 1,20000))): #sys.maxunicode is SLOW
            unicode_category[unicodedata.category(c)] += c

        #id_start = Lu, Ll, Lt, Lm, Lo, Nl, the underscore, and characters with the Other_ID_Start property>
        validIDStart = (unicode_category["Lu"] + unicode_category["Ll"] +
            unicode_category["Lt"] + unicode_category["Lm"] + unicode_category["Lo"] + 
            unicode_category["Nl"] + "_")
        #id_continue = id_start, plus Mn, Mc, Nd, Pc and others with the Other_ID_Continue property>
        validID = (validIDStart + unicode_category["Mn"] + unicode_category["Mc"] + 
            unicode_category["Nd"] + unicode_category["Pc"])

    #Yield the strings, starting with 1 character strings
    for c in validIDStart:
        if c in keyword.kwlist:
            continue #Skip keywords
        yield c

    #Yield 2+ character strings
    tailLength = 1
    while True:
        for c in validIDStart:
            for c2 in itertools.combinations_with_replacement(validID, tailLength):
                c2 = "".join(c2)
                if c + c2 in keyword.kwlist:
                    continue #Skip keywords
                yield c + c2

        tailLength += 1

class FrameTrackingNodeVisitor(ast.NodeVisitor):
    """
    A NodeTransformer that builds a graph of all relevant identifiers, and their
    relevant scoepes
    Do not inherit from this but instead instantiate it. It cannot give an accurate
    picture for a given identifier if scope usages occur out of order between definition
    and usage
    """

    #Keeps track of a stack frame and all the identifiers that exist in that frame
    class Frame:
        __slots__ = ["source", "parent", "children", "ids"]
        def __init__(self, source=None, parent=None, children=None, ids=None):
            self.source = source
            self.parent = parent
            self.children = children
            self.ids = ids
        def __str__(self):
            return str(self.source.__class__.__name__) + " {\n  " + \
                "\n  ".join([s + ": " + str(i) for s, i in self.ids.items()]) + \
                "\n}" + (" => " + \
                "\n    ".join(" && ".join([str(s) for s in self.children]).split("\n")) if self.children else "")
                
        def __repr__(self):
            return str(self)

    #Keeps track of data related to a scoped identifier that lives in a
    #a stack frame.
    #Source is the node the identifier came from
    #Parent is the parent Frame
    #Ctx is ast.Load or ast.Store to catalog if it will push to the stack or not
    #Value is the return from onEnterStackFrame that was stored for this scoped identifier
    class FrameEntry:
        __slots__ = ["source", "parent", "ctx", "value"]
        def __init__(self, source=None, parent=None, ctx=None, value=None):
            self.source = source
            self.parent = parent
            self.ctx = ctx
            self.value = value
        def __str__(self):
            return str(self.source.__class__.__name__) + \
                (("(" + str(self.ctx.__class__.__name__) + ")") if self.ctx else "") + \
                (("=" + str(self.value)) if self.value else "")
        def __repr__(self):
            return str(self)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        #The stack of scope FrameTrackingNodeTransformer.Frame's that hold the identifiers
        #for a certain scope. All identifiers are stored in .ids as .FrameEntry's
        self._frameStack = []
        self._rootFrame = None

        #Setup initial frameStack
        self._appendFrame(None) #Builtins has no Node
        for b in dir(builtins) + ["__file__"]:
            self._appendFrameEntry(self._frameStack[0], None, b)

    def _appendFrame(self, node):
        """
        Appends a new frame to _frameStack to keep track of new identifiers
        in the newly parsed scope
        """
        if logLevel > 0:
            print("[FrameTrack][+Frame]: " + str(node.__class__.__name__) + " \"" +
                (node.name if hasattr(node, "name") else "") + "\"")

        #Frame
        frame = FrameTrackingNodeVisitor.Frame(
            source=node,
            parent=self._frameStack[-1] if self._frameStack else None,
            children=[],
            ids={})

        #Bookkeeping
        if not self._rootFrame:
            self._rootFrame = frame
        if self._frameStack: #len()
            self._frameStack[-1].children.append(frame)

        self._frameStack.append(frame)

    def _createsFrame(self, node):
        """
        Whether or not the given node should be creating a stack frame
        """
        #todo: Comprehensions need to push a frame too
        return isinstance(node, (ast.FunctionDef, ast.ClassDef, ast.Module))

    def _popFrame(self):
        """
        Pops the top stack frame
        """
        if logLevel > 0:
            print("[FrameTrack][-Frame]")

        rmFrame = self._frameStack.pop()
        return rmFrame

    def _appendFrameEntry(self, frame, node, strId, ctx=ast.Store(), value=None):
        """Writes an entry for the given identifier, into the given frame"""
        if strId in frame.ids:
            #Only record the first instance as subsequent instances arent _really_
            #allowed to redefine the scope. A global statement after a local assign
            #is ignored (Python 3.5). A local assign after a global ctx.Load is an error.
            #Im not really sure about nonlocal but if it acts like global then we
            #should be fine
            return

        frame.ids[strId] = FrameTrackingNodeVisitor.FrameEntry(
            source=node,
            parent=frame,
            ctx=ctx,
            value=value
            )

        if logLevel > 0:
            print("[FrameTrack][+Entry]: " + node.__class__.__name__ + " \"" + strId +
                "\" => \"" + str(value) + "\"")


    def _findContextFrameForId(self, strId):
        """
        Manually searches for the first frame for the given identifier,
        None if not found
        """
        for frame in reversed(self._frameStack):
            if strId in frame.ids:
                return frame
        return None

    def getIdsFromNode(self, node):
        """
        Python ast does not make it easy to act simply on the identifiers of a node
        (and you have to switch over node types and get specific attributes). To
        ease this pain we return an array of all the identifiers flatly in a node
        and provide a set() function that takes a similar array.
        TODO: Properties that are not defined (that are None) just come back as blanks,
        do we want this? Do we want to be able to set the names of ids that aren't
        a thing
        TODO: If we need more granularity, we need to edit how this works (would need
        to return key'd objects)
        """
        #Handle global/nonlocal (Python3) statement
        if isinstance(node, (ast.Global, ast.Nonlocal)):
            return node.names
        #Handle import alias's
        elif isinstance(node, ast.alias):
            return [node.name if node.asname is None else node.asname]
        #Except
        elif isinstance(node, ast.ExceptHandler):
            #Is raw only in Python 3, Name node in Python 2, None if not included
            return [node.name] if hasattr(node, "name") and type(node.name) == str else []
        #FunctionDef or ClassDef
        elif isinstance(node, (ast.FunctionDef,ast.ClassDef)):
            return [node.name]
        #arguments
        #Up to Python 3.3, ast.arguments has kwargs and args as a raw string and not
        #as an ast.arg(which we handle in another case) so handle it
        elif isinstance(node, ast.arguments):
            ret = []
            if hasattr(node, "args") and type(node.args) == str:
                ret.append(node.args)
            if hasattr(node, "kwargs") and type(node.kwargs) == str:
                ret.append(node.kwargs)
        #TODO:keyword (in Python <3.3)
        #arg
        elif isinstance(node, ast.arg):
            return [node.arg] if type(node.arg) == str else []
        #TODO: Annotations (for everything x:)
        #Handle Name (which handles anything that doesn't use raw strings)
        elif isinstance(node, ast.Name):
            return [node.id]
        return []

    def setIdsOnNode(self, node, names):
        """
        Tightly coupled to the implementation of getIdsFromNode. It must unpack
        it the EXACT same way
        """
        if not names:
            return #Passed an empty array, don't do anything

        if isinstance(node, (ast.Global, ast.Nonlocal)):
            node.names = names
        elif isinstance(node, (ast.alias)):
            if node.asname is None:
                node.name = names[0]
            else:
                node.asname = names[0]
        elif isinstance(node, (ast.FunctionDef,ast.ClassDef,ast.ExceptHandler)):
            node.name = names[0]
        elif isinstance(node, ast.arguments):
            #pop in reverse order
            if hasattr(node, "kwargs") and type(node.kwargs) == str:
                node.kwargs = names.pop()
            if hasattr(node, "args") and type(node.args) == str:
                node.args = names.pop()
        elif isinstance(node, ast.arg):
            node.arg = names[0]
        elif isinstance(node, ast.Name):
            node.id = names[0]

    def _handleEnterNode(self, node):
        """
        Takes a new node and appends, modifies, or pops the identifiers in that
        node to the appropriate stack frame
        """
        #Amazingly helpful and even necessary reference/reading to edit
        #this section would be:
        #
        #http://greentreesnakes.readthedocs.io/en/latest/nodes.html#
        #
        #as it demonstrates how the ast changes through Python versions
        #and which identifiers come up as node.Name and which come up as
        #a raw string on a field (Ctrl+F raw)

        #SCOPE DEFINING CASES (nodes that have an identifier that will make it add
        #to the current scope)
        #Handle global/nonlocal (Python3) statement
        if isinstance(node, (ast.Global, ast.Nonlocal)):
            frame = self._frameStack[1] #For global statement, always use the same stack frame
            #global_stmt ::=  "global" identifier ("," identifier)*
            for strId in node.names:
                if isinstance(node, ast.Nonlocal):
                    #Find scope for nonlocal argument, if None then TODO
                    frame = self._findContextFrameForId(strId)
                    if frame is None:
                        raise NotImplementedError("TODO: No scope for nonlocal declaration, what do?")

                #If in the current scope is already defined (the assigned and then used the statement)
                #do what python does and warn but leave it as local
                #This is Python 3.5 behavior so this might need to be changed if ever a problem
                if self._findContextFrameForId(strId) != frame:
                    print("WARN: Global/nonlocal found when variable already in local scope")
                else:
                    self._appendFrameEntry(frame, node, strId)
        #TODO: Annotations (for everything x:)
        #Handle Name (which handles anything that doesn't use raw strings)
        elif isinstance(node, ast.Name):
            if isinstance(node.ctx, ast.Load):
                self._appendFrameEntry(self._frameStack[-1], node, node.id, node.ctx)
            #Store
            #Or Param (Python 2 ast.arg Name node ctx, instead of raw string)
            elif isinstance(node.ctx, (ast.Store,ast.Param)):
                self._appendFrameEntry(self._frameStack[-1], node, node.id, ast.Store())
            #Delete
            #ignore these, consider Python will throw an error and they don't modify scope
        #For everything else that has an ID, rely on getIdsFromNode to get the
        #names and handle normally
        else:
            ids = self.getIdsFromNode(node)
            for strId in ids:
                self._appendFrameEntry(self._frameStack[-1], node, strId)

        if self._createsFrame(node):
            self._appendFrame(node)

    def _handleLeaveNode(self, node):
        """
        Takes a node we're leaving and, if necessary, performs cleanup
        related to moving it off of the stack
        """
        if self._createsFrame(node):
            self._popFrame()

    def generic_visit(self, node):
        self._handleEnterNode(node)
        super().generic_visit(node)
        self._handleLeaveNode(node)

    #Querying out internal data
    def _getRecreatedFrameStack(self, nodeStack):
        """
        Returns the recreated _frameStack for a given nodeStack
        """
        #Find the frame in question by traversing through the frames
        #using the stack frame creating nodes to compare to those
        #previously bookmarked
        #TODO: This could be better an iterator, not a list return
        frameStack = [self._rootFrame]
        for node in filter(self._createsFrame, nodeStack):
            frame = frameStack[-1]
            frame = next(filter(lambda f: f.source == node, frame.children))
            frameStack.append(frame)
        return frameStack

    def _getEntryForId(self, nodeStack, strId):
        """
        Gets the FrameEntry for a given ID in the passed nodeStack
        """
        #Reverse search for the strId in the given frame stack
        for frame in reversed(self._getRecreatedFrameStack(nodeStack)):
            if strId in frame.ids:
                entry = frame.ids[strId]
                if isinstance(entry.ctx, ast.Store):
                    #Only ast.Store will actually define the scope for an ID
                    return entry

        #This happens if the identifier was not seen in the given scope stack.
        #Most likely passing something erroneously in
        print("WARN: Queried identifier \"" + strId + "\" has not been seen at the given scope stack")

    def getValueForId(self, nodeStack, strId):
        return self._getEntryForId(nodeStack, strId).value

    def setValueForId(self, nodeStack, strId, value):
        self._getEntryForId(nodeStack, strId).value = value

    def getSourceForId(self, nodeStack, strId):
        return self._getEntryForId(nodeStack, strId).source

    def getStackSourceForId(self, nodeStack, strId):
        return self._getEntryForId(nodeStack, strId).parent.source

    def getAllIdsAtScope(self, nodeStack):
        """
        Given a scope (nodeStack), return all the IDs we can see from here
        """
        frameStack = self._getRecreatedFrameStack(nodeStack)
        ids = []
        for frame in reversed(frameStack):
            ids += frame.ids.keys()
        return ids


    def isIdBuiltin(self, nodeStack, strId):
        return self._getEntryForId(nodeStack, strId).parent == self._rootFrame

class ObfuscationTransformer(ast.NodeTransformer):
    """
    Parses out things that obfuscate our code, 
    NOTE: Comments won't be in the AST anyway, so no worries
    """
    def __init__(self, *args, **kwargs):
        self._frameTrack = None
        self._nodeStack = []
        #TODO: Name should eventually be unique per scope, as we
        #can better obfuscate by using the same names in scopes that
        #don't touch each other
        self._name = validIdentifierIterator()
        super().__init__(*args, **kwargs)

    def getMangledName(self, nodeStack, strId):
        """
        Determine whether a strId used somewhere should be
        mangled
        """
        alreadyMangledName = self._frameTrack.getValueForId(nodeStack, strId)
        if alreadyMangledName:
            return alreadyMangledName #It has a mangled name, use it
        if alreadyMangledName == False:
            return False #It was instructed to not mangle

        if self._frameTrack.isIdBuiltin(nodeStack, strId):
            #Dont rename builtins
            self._frameTrack.setValueForId(nodeStack, strId, False)
            return False

        stackNode = self._frameTrack.getStackSourceForId(nodeStack, strId) #ClassDef, FunctionDef, etc that defined the stack
        sourceNode = self._frameTrack.getSourceForId(nodeStack, strId) #The node that the id came from
        if isinstance(stackNode, (ast.ClassDef,ast.Module)):
            #Anything in the class namespace (static variables, methods)
            #and anything in the module namespace (will probs be exported)
            #should not be mangled
            self._frameTrack.setValueForId(nodeStack, strId, False)
            return False
        elif isinstance(sourceNode, ast.alias):
            #An imported name, don't mangle those
            self._frameTrack.setValueForId(nodeStack, strId, False)
            return False
        elif isinstance(sourceNode, ast.arg) and hasattr(nodeStack[-1], "defaults") and nodeStack[-1].defaults:
            #An argument node with keyword args, don't mangle the keyword args
            #Slice the keyword arguments
            #TODO: I have no idea if this functions in not Python 3.5
            print("ASD")
            argumentsNode = nodeStack[-1]
            #Slice the number of default nodes from the end
            kwStrs = list(map(lambda n: n.arg, argumentsNode.args[-len(argumentsNode.defaults):]))
            print(kwStrs, strId, strId in kwStrs)
            if strId in kwStrs:
                self._frameTrack.setValueForId(nodeStack, strId, False)
                return False

        #Otherwise, return the name we're mangling to for this
        #string ID and store it
        #Make sure the mangleName isn't in the current scope already (as an unmangled name)
        ids = self._frameTrack.getAllIdsAtScope(nodeStack)
        mangledName = next(self._name)
        while mangledName in ids:
            mangledName = next(self._name)
        self._frameTrack.setValueForId(nodeStack, strId, mangledName)
        return mangledName

    def generic_visit(self, node):
        #Debug output
        debugMsg = node.__class__.__name__

        #Remove docstrings
        if (isinstance(node, ast.Expr) and 
            isinstance(self._nodeStack[-1], 
                (ast.FunctionDef,ast.ClassDef,ast.Module)) and 
            isinstance(node.value, ast.Str)):
            return ast.Pass()

        #Mangle names
        ids = self._frameTrack.getIdsFromNode(node)
        if ids:
            debugMsg += ": "
            debugMsg += str(ids) if ids else None
        for idx, strId in enumerate(ids):
            mangleTo = self.getMangledName(self._nodeStack, strId)
            if not mangleTo:
                continue
            ids[idx] = mangleTo
        self._frameTrack.setIdsOnNode(node, ids)
        if ids:
            debugMsg += " => "
            debugMsg += str(ids) if ids else None
        if logLevel > 0:
            print(debugMsg)

        #Go in to deeper nodes
        self._nodeStack.append(node)
        super().generic_visit(node)
        self._nodeStack.pop()
        
        return node

    def visit(self, node):
        if not self._frameTrack:
            #Prime self._frameTrack with our node
            self._frameTrack = FrameTrackingNodeVisitor()
            self._frameTrack.visit(node)
        return super().visit(node)

def obfuscateString(s):
    sAst = ast.parse(s)
    sAst = ObfuscationTransformer().visit(sAst)
    return astunparse.unparse(sAst)

def obfuscateFile(fp):
    f = open(fp, "r")
    s = f.read()
    f.close()
    s = obfuscateString(s)
    f = open(fp, "w")
    f.write(s)
    f.close()