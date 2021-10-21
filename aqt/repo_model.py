import json
from typing import Dict, Generator, List, Optional, Tuple

from aqt.exceptions import AqtException, CliInputError
from aqt.metadata import SimpleSpec, Version


class SchemaError(AqtException):
    pass


class Schema:
    ALLOWED_VALUES = {"host": ["windows", "linux", "mac"], "bits": ["64", "32"]}

    def __init__(
        self,
        tool_name: str,
        schema_name: str,
        args: List[str],
        url_template: str,
        allowed_values: Optional[Dict[str, List[str]]] = None,
        conversions: Dict[str, Dict[str, str]] = None,
    ):
        self.tool_name = tool_name
        self.schema_name = schema_name
        self.args: List[str] = args
        self.url_template: str = url_template
        self.allowed_values: Dict[str, List[str]] = allowed_values if allowed_values else {}
        self.name_converters: Dict[str, Dict[str, str]] = conversions

    def fill_template(self, args: Dict[str, str]) -> str:
        variables = {k: v for k, v in args.items()}

        def choose_translation(key: str, _conversion: Dict[str, any]) -> any:
            """Picks the right conversion out of a dictionary for a particular key"""
            if key == "semver":
                # We will match based on SimpleSpecs in the _conversion
                for k, v in _conversion.items():
                    if semver in SimpleSpec(k):
                        return v
                raise SchemaError(f"Schema contains no resolution for version {semver}")
            # Otherwise, just pick the matching key
            return _conversion[variables[key]]

        def recursive_translate(translation_key: str, _conversion: Dict[str, any]) -> Tuple[str, str]:
            if "-to-" not in translation_key:
                raise SchemaError("Schema contains unrecognized key")
            _from, _to = translation_key.split("-to-")
            assert isinstance(_from, str) and isinstance(_to, str)
            translation = choose_translation(_from, _conversion)  # _conversion[variables[_from]]
            if isinstance(translation, str):
                return _to, translation
            if not isinstance(translation, dict):
                raise SchemaError("Translator object is neither a string nor a dictionary")
            # Get the first and only available key
            keys = list(translation.keys())
            if len(keys) != 1:
                raise SchemaError("Translator object should only have one key available")
            return recursive_translate(keys[0], translation[keys[0]])

        if "semver" in args:
            semver = Version(args["semver"])
            variables["major_minor_semver"] = f"{semver.major}.{semver.minor}"
            variables["semver_underscores"] = f"{semver.major}_{semver.minor}_{semver.patch}"
        for key, conversion in self.name_converters.items():
            variable_key, value = recursive_translate(key, conversion)
            variables[variable_key] = value

        return self.url_template.format(**variables)

    def list_allowed_values_for(self, key: str) -> List[str]:
        if key in self.allowed_values.keys():
            return self.allowed_values[key]
        if key in Schema.ALLOWED_VALUES:
            return Schema.ALLOWED_VALUES[key]
        raise KeyError(f"Allowed values for the key '{key}' are not tracked.")

    def yield_urls(self, args: List[str]) -> Generator[str, None, None]:
        if len(args) != len(self.args):
            raise CliInputError("Wrong number of arguments!")

        # Use slate pattern to fill in arguments when an arg == "all"
        def helper(args_dict: Dict[str, str], index: int) -> Generator[str, None, None]:
            if index == len(args):
                yield f"{self.tool_name}/{self.fill_template(args_dict)}"
                return
            # fill in the next argument
            arg, arg_name = args[index], self.args[index]
            if arg == "all":
                for allowed_value in self.list_allowed_values_for(arg_name):
                    args_dict[arg_name] = allowed_value
                    yield from helper(args_dict, index + 1)
                args_dict.pop(arg_name)
            else:
                args_dict[arg_name] = arg
                yield from helper(args_dict, index + 1)
                args_dict.pop(arg_name)

        yield from helper({}, 0)


class RepoModel:
    def __init__(self, json_definition: str):
        self.definition: Dict = json.loads(json_definition)

    def list_tool_names(self) -> List[str]:
        return list(self.definition.keys())

    def list_schemas(self, tool_name: str) -> List[str]:
        return list(self.definition[tool_name].keys())

    def get_schema(self, tool_name: str, schema: str) -> Schema:
        s: Dict = self.definition[tool_name][schema]
        return Schema(
            tool_name=tool_name,
            schema_name=schema,
            args=s.pop("args"),
            url_template=s.pop("url_template"),
            allowed_values=s.pop("allowed_values", {}),
            conversions=s,
        )
