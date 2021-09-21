import logging
import os
from collections import defaultdict
from pathlib import Path
from typing import Union, Dict, List, Any
from functools import lru_cache
from dataclasses import dataclass, field

import click
import yaml

from linkml_runtime.linkml_model.meta import SchemaDefinition, ClassDefinition, SlotDefinition
from linkml_runtime.utils.formatutils import camelcase, lcamelcase
from linkml.utils.generator import Generator, shared_arguments

from linkml.generators.graphqlgen import GraphqlGenerator
from linkml.generators.jsonldcontextgen import ContextGenerator
from linkml.generators.jsonldgen import JSONLDGenerator
from linkml.generators.jsonschemagen import JsonSchemaGenerator
from linkml.generators.markdowngen import MarkdownGenerator
from linkml.generators.owlgen import OwlSchemaGenerator
from linkml.generators.prefixmapgen import PrefixGenerator
from linkml.generators.protogen import ProtoGenerator
from linkml.generators.pythongen import PythonGenerator
from linkml.generators.rdfgen import RDFGenerator
from linkml.generators.shexgen import ShExGenerator
from linkml.generators.sqlddlgen import SQLDDLGenerator
from linkml.generators.excelgen import ExcelGenerator
from linkml.generators.javagen import JavaGenerator

GEN_MAP = {
    'graphql': (GraphqlGenerator, 'graphql/{name}.graphql', {}),
    'jsonldcontext': (ContextGenerator, 'jsonld/{name}.context.jsonld', {}),
    'jsonld': (JSONLDGenerator, 'jsonld/{name}.jsonld', {'context': '{parent}/{name}.context.jsonld'}),
    'jsonschema': (JsonSchemaGenerator, 'jsonschema/{name}.schema.json', {}),
    'markdown': (MarkdownGenerator, 'docs/',
                 {'directory': '{parent}',
                  'index_file': '{name}.md'}),
    'owl': (OwlSchemaGenerator, 'owl/{name}.owl.ttl', {}),
    'prefixmap': (PrefixGenerator, 'prefixmap/{name}.yaml', {}),
    'proto': (ProtoGenerator, 'protobuf/{name}.proto', {}),
    'python': (PythonGenerator, '{name}.py', {}),
#    'rdf': (RDFGenerator, 'rdf/{name}.ttl', {}),
#    'rdf': (RDFGenerator, 'rdf/{name}.ttl', {'context': '{parent}/../jsonld/{name}.context.jsonld'}),
    'shex': (ShExGenerator, 'shex/{name}.shexj', {}),
    'sqlddl': (SQLDDLGenerator, 'sqlschema/{name}.sql', {}),
    'java': (SQLDDLGenerator, 'java/{name}.sql', {}),
    'excel': (SQLDDLGenerator, 'excel/{name}.xlsx', {}),
}

@lru_cache()
def get_local_imports(schema_path: str, dir: str):
    print(f'GETTING IMPORTS = {schema_path}')
    all_imports = [schema_path]
    with open(schema_path) as stream:
        with open(schema_path) as stream:
            schema = yaml.safe_load(stream)
            for imp in schema.get('imports', []):
                imp_path = os.path.join(dir, imp) + '.yaml'
                print(f' IMP={imp} //  path={imp_path}')
                if os.path.isfile(imp_path):
                    all_imports += get_local_imports(imp_path, dir)
    return all_imports

@dataclass
class ProjectConfiguration:
    """
    Global project configuration, and per-generator configurations
    """
    directory: str = 'tmp'
    generator_args: Dict[str, Dict[str,Any]] = field(default_factory=lambda: defaultdict(dict))
    includes: List[str] = None
    excludes: List[str] = None

class ProjectGenerator:

    def generate(self, schema_path: str, config: ProjectConfiguration = ProjectConfiguration()):
        if config.directory is None:
            raise Exception(f'Must pass directory')
        Path(config.directory).mkdir(parents=True, exist_ok=True)
        all_schemas = get_local_imports(schema_path, os.path.dirname(schema_path))
        print(f'ALL_SCHEMAS = {all_schemas}')
        for gen_name, (gen_cls, gen_path_fmt, default_gen_args) in GEN_MAP.items():
            if config.includes is not None and config.includes != [] and gen_name not in config.includes:
                logging.info(f'Skipping {gen_name} as not in inclusion list: {config.includes}')
                continue
            if config.excludes is not None and gen_name in config.excludes:
                logging.info(f'Skipping {gen_name} as it is in exclusion list')
                continue
            logging.info(f'Generating: {gen_name}')
            for local_path in all_schemas:
                logging.info(f' SCHEMA: {local_path}')
                name = os.path.basename(local_path).replace('.yaml', '')
                gen_path = gen_path_fmt.format(name=name)
                gen_path_full = f'{config.directory}/{gen_path}'
                parts = gen_path_full.split('/')
                parent_dir = '/'.join(parts[0:-1])
                logging.info(f' PARENT={parent_dir}')
                Path(parent_dir).mkdir(parents=True, exist_ok=True)
                gen_path_full = '/'.join(parts)
                all_gen_args = {**default_gen_args, **config.generator_args.get(gen_name, {})}
                gen: Generator
                gen = gen_cls(local_path, **all_gen_args)
                serialize_args = {'mergeimports': False}
                for k, v in all_gen_args.items():
                    serialize_args[k] = v.format(name=name, parent=parent_dir)
                logging.info(f' ARGS: {serialize_args}')
                gen_dump = gen.serialize(**serialize_args)
                if parts[-1] != '':
                    # markdowngen does not write to a file
                    logging.info(f'  WRITING TO: {gen_path_full}')
                    with open(gen_path_full, 'w') as stream:
                        stream.write(gen_dump)

@click.command()
@click.option("--dir", "-d",
              help="directory in which to place generated files. E.g. linkml_model, biolink_model")
@click.option("--generator-arguments", "-A",
              help="yaml configuration for generators")
@click.option("--config-file", "-C",
              type=click.File('rb'),
              help="path to yaml configuration")
@click.option("--exclude", "-X",
              multiple=True,
              help="list of artefacts to be excluded")  # TODO: make this an enum
@click.option("--include", "-I",
              multiple=True,
              help="list of artefacts to be included. If not set, defaults to all")  # TODO: make this an enum
@click.argument('yamlfile')
def cli(yamlfile, dir, exclude: List[str], include: List[str], config_file, generator_arguments: str, **kwargs):
    """
    Generate an entire project LinkML schema

    Generate all downstream artefacts using default configuration:

       gen-project -d . personinfo.yaml

    Exclusion lists: all except ShEx:

       gen-project --exclude shex -d . personinfo.yaml

    Inclusion lists: only jsonschema and python:

       gen-project -I python -I jsonschema -d . personinfo.yaml

    Configuration, on command line:

        gen-project -A 'jsonschema: {top_class: Container}' -d . personinfo.yaml

    Configuration, via yaml file:

        gen-project --config config.yaml personinfo.yaml

    config.yaml:

        directory: .
        generator_args:
          json_schema:
            top_class: Container

    """
    logging.basicConfig(level=logging.INFO)
    project_config = ProjectConfiguration()
    if config_file is not None:
        for k, v in yaml.safe_load(config_file).items():
            setattr(project_config, k, v)
    if exclude:
        project_config.excludes = list(exclude)
    if include:
        project_config.includes = list(include)
    if generator_arguments is not None:
        try:
            project_config.generator_args = yaml.safe_load(generator_arguments)
        except Exception:
            raise Exception(f'Argument must be a valid YAML blob')
        logging.info(f'generator args: {project_config.generator_args}')
    if dir is not None:
        project_config.directory = dir
    gen = ProjectGenerator()
    gen.generate(yamlfile, project_config)


if __name__ == '__main__':
    cli()





