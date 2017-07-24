# coding: utf-8
import pytest

from jsl import (Document, BaseSchemaField, StringField, ArrayField,
                 DocumentField, IntField, DateTimeField, NumberField,
                 DictField, NotField, AllOfField, AnyOfField, OneOfField,
                 DEFAULT_ROLE)
from jsl.roles import Var, Scope, not_, Resolution
from jsl.exceptions import SchemaGenerationException

from util import normalize, sort_required_keys


def test_var():
    value_1 = object()
    value_2 = object()
    value_3 = object()
    var = Var([
        ('role_1', value_1),
        ('role_2', value_2),
        (not_('role_3'), value_3),
    ])
    assert len(var.values) == 3
    for matcher, value in var.values:
        assert callable(matcher)
        assert type(value) == object

    assert var.resolve('role_1') == Resolution(value_1, 'role_1')
    assert var.resolve('role_2') == Resolution(value_2, 'role_2')
    assert var.resolve('default') == Resolution(value_3, 'default')

    var = Var([
        (not_('role_3'), value_3),
        ('role_1', value_1),
        ('role_2', value_2),
    ])
    assert var.resolve('role_1') == Resolution(value_3, 'role_1')
    assert var.resolve('role_2') == Resolution(value_3, 'role_2')
    assert var.resolve('default') == Resolution(value_3, 'default')
    assert var.resolve('role_3') == Resolution(None, 'role_3')

    var = Var([
        ('role_1', value_1),
        ('role_2', value_2),
    ], propagate='role_2')
    assert callable(var.propagate)


DB_ROLE = 'db'
REQUEST_ROLE = 'request'
RESPONSE_ROLE = 'response'
PARTIAL_RESPONSE_ROLE = RESPONSE_ROLE + '_partial'


def test_helpers():
    when = lambda *args: Var({
        not_(*args): False
    }, default=True)

    assert when(RESPONSE_ROLE).resolve(RESPONSE_ROLE).value
    assert not when(RESPONSE_ROLE).resolve(REQUEST_ROLE).value


def test_scope():
    scope = Scope(DB_ROLE)
    f = StringField()
    scope.login = f
    assert scope.login == f

    assert scope.__fields__ == {
        'login': f,
    }

    with pytest.raises(AttributeError):
        scope.gsomgsom


def test_scopes_basics():
    when_not = lambda *args: Var({
        not_(*args): True
    }, default=False)

    class Message(Document):
        with Scope(DB_ROLE) as db:
            db.uuid = StringField(required=True)
        created_at = IntField(required=when_not(PARTIAL_RESPONSE_ROLE, REQUEST_ROLE))
        text = StringField(required=when_not(PARTIAL_RESPONSE_ROLE))
        field_that_is_never_present = Var({
            'NEVER': StringField(required=True)
        })

    class User(Document):
        class Options(object):
            roles_to_propagate = not_(PARTIAL_RESPONSE_ROLE)

        with Scope(DB_ROLE) as db:
            db._id = StringField(required=True)
            db.version = StringField(required=True)
        with Scope(lambda r: r.startswith(RESPONSE_ROLE) or r == REQUEST_ROLE) as response:
            response.id = StringField(required=when_not(PARTIAL_RESPONSE_ROLE))
        with Scope(not_(REQUEST_ROLE)) as not_request:
            not_request.messages = ArrayField(DocumentField(Message), required=when_not(PARTIAL_RESPONSE_ROLE))

    resolution = Message.resolve_field('text')
    assert resolution.value == Message.text
    assert resolution.role == DEFAULT_ROLE

    resolution = Message.resolve_field('field_that_is_never_present')
    assert resolution.value is None
    assert resolution.role == DEFAULT_ROLE

    resolution = Message.resolve_field('non-existent')
    assert resolution.value is None
    assert resolution.role == DEFAULT_ROLE

    schema = User.get_schema(role=DB_ROLE)
    expected_required = sorted(['_id', 'version', 'messages'])
    expected_properties = {
        '_id': {'type': 'string'},
        'version': {'type': 'string'},
        'messages': {
            'type': 'array',
            'items': {
                'type': 'object',
                'additionalProperties': False,
                'properties': {
                    'created_at': {'type': 'integer'},
                    'text': {'type': 'string'},
                    'uuid': {'type': 'string'}
                },
                'required': sorted(['uuid', 'created_at', 'text']),
            },
        },
    }
    assert sorted(schema['required']) == expected_required
    assert sort_required_keys(schema['properties']) == sort_required_keys(expected_properties)
    assert dict(User.resolve_and_iter_fields(DB_ROLE)) == {
        '_id': User.db._id,
        'version': User.db.version,
        'messages': User.not_request.messages,
    }

    schema = User.get_schema(role=REQUEST_ROLE)
    expected_required = sorted(['id'])
    expected_properties = {
        'id': {'type': 'string'},
    }
    assert sorted(schema['required']) == expected_required
    assert sort_required_keys(schema['properties']) == sort_required_keys(expected_properties)
    assert dict(User.resolve_and_iter_fields(REQUEST_ROLE)) == {
        'id': User.response.id,
    }

    schema = User.get_schema(role=RESPONSE_ROLE)
    expected_required = sorted(['id', 'messages'])
    expected_properties = {
        'id': {'type': 'string'},
        'messages': {
            'type': 'array',
            'items': {
                'type': 'object',
                'additionalProperties': False,
                'properties': {
                    'created_at': {'type': 'integer'},
                    'text': {'type': 'string'},
                },
                'required': sorted(['created_at', 'text']),
            },
        },
    }
    assert sorted(schema['required']) == expected_required
    assert sort_required_keys(schema['properties']) == sort_required_keys(expected_properties)
    assert dict(User.resolve_and_iter_fields(RESPONSE_ROLE)) == {
        'id': User.response.id,
        'messages': User.not_request.messages,
    }

    schema = User.get_schema(role=PARTIAL_RESPONSE_ROLE)
    expected_properties = {
        'id': {'type': 'string'},
        'messages': {
            'type': 'array',
            'items': {
                'type': 'object',
                'additionalProperties': False,
                'properties': {
                    'created_at': {'type': 'integer'},
                    'text': {'type': 'string'},
                },
                'required': sorted(['created_at', 'text']),
            },
        },
    }
    assert 'required' not in schema
    assert sort_required_keys(schema['properties']) == sort_required_keys(expected_properties)
    assert dict(Message.resolve_and_iter_fields(PARTIAL_RESPONSE_ROLE)) == {
        'created_at': Message.created_at,
        'text': Message.text,
    }


def test_base_field():
    _ = lambda value: Var({'role_1': value})
    field = BaseSchemaField(default=_(lambda: 1), enum=_(lambda: [1, 2, 3]), title=_('Title'),
                            description=_('Description'))
    schema = field._update_schema_with_common_fields({})
    assert schema == {}

    schema = field._update_schema_with_common_fields(schema, role='role_1')
    assert schema == {
        'title': 'Title',
        'description': 'Description',
        'enum': [1, 2, 3],
        'default': 1,
    }


def test_string_field():
    _ = lambda value: Var({'role_1': value})
    field = StringField(format=_('date-time'), min_length=_(1), max_length=_(2))
    assert normalize(field.get_schema()) == normalize({
        'type': 'string'
    })
    assert normalize(field.get_schema(role='role_1')) == normalize({
        'type': 'string',
        'format': 'date-time',
        'minLength': 1,
        'maxLength': 2,
    })

    with pytest.raises(ValueError) as e:
        StringField(pattern=_('('))
    assert str(e.value).startswith('Invalid regular expression:')


def test_array_field():
    s_f = StringField()
    n_f = NumberField()
    field = ArrayField(Var({
        'role_1': s_f,
        'role_2': n_f,
    }))
    schema = normalize(field.get_schema(role='role_1'))
    assert normalize(schema['items']) == s_f.get_schema()

    schema = normalize(field.get_schema(role='role_2'))
    assert schema['items'] == n_f.get_schema()

    schema = normalize(field.get_schema())
    assert 'items' not in schema

    _ = lambda value: Var({'role_1': value})
    field = ArrayField(s_f, min_items=_(1), max_items=_(2), unique_items=_(True), additional_items=_(True))
    assert normalize(field.get_schema()) == normalize({
        'type': 'array',
        'items': s_f.get_schema(),
    })
    assert field.get_schema(role='role_1') == normalize({
        'type': 'array',
        'items': s_f.get_schema(),
        'minItems': 1,
        'maxItems': 2,
        'uniqueItems': True,
        'additionalItems': True,
    })


def test_dict_field():
    s_f = StringField()
    _ = lambda value: Var({'role_1': value})
    field = DictField(properties=Var(
        {
            'role_1': {'name': Var({'role_1': s_f})},
            'role_2': {'name': Var({'role_2': s_f})},
        },
        propagate='role_1'
    ), pattern_properties=Var(
        {
            'role_1': {'.*': Var({'role_1': s_f})},
            'role_2': {'.*': Var({'role_2': s_f})},
        },
        propagate='role_1'
    ), additional_properties=_(s_f), min_properties=_(1), max_properties=_(2))
    assert normalize(field.get_schema()) == normalize({
        'type': 'object'
    })
    assert normalize(field.get_schema(role='role_1')) == normalize({
        'type': 'object',
        'properties': {
            'name': s_f.get_schema(),
        },
        'patternProperties': {
            '.*': s_f.get_schema(),
        },
        'additionalProperties': s_f.get_schema(),
        'minProperties': 1,
        'maxProperties': 2,
    })
    assert normalize(field.get_schema(role='role_2')) == normalize({
        'type': 'object',
        'properties': {},
        'patternProperties': {},
    })


@pytest.mark.parametrize(('keyword', 'field_cls'),
                         [('oneOf', OneOfField), ('anyOf', AnyOfField), ('allOf', AllOfField)])
def test_keyword_of_fields(keyword, field_cls):
    s_f = StringField()
    n_f = NumberField()
    i_f = IntField()
    field = field_cls([n_f, Var({'role_1': s_f}), Var({'role_2': i_f})])
    assert normalize(field.get_schema()) == {
        keyword: [n_f.get_schema()]
    }
    assert normalize(field.get_schema(role='role_1')) == {
        keyword: [n_f.get_schema(), s_f.get_schema()]
    }
    assert normalize(field.get_schema(role='role_2')) == {
        keyword: [n_f.get_schema(), i_f.get_schema()]
    }

    field = field_cls(Var({
        'role_1': [n_f, Var({'role_1': s_f}), Var({'role_2': i_f})],
        'role_2': [Var({'role_2': i_f})],
    }, propagate='role_1'))
    assert normalize(field.get_schema(role='role_1')) == {
        keyword: [n_f.get_schema(), s_f.get_schema()]
    }
    with pytest.raises(SchemaGenerationException):
        field.get_schema(role='role_2')


def test_not_field():
    s_f = StringField()
    field = NotField(Var({'role_1': s_f}))
    assert normalize(field.get_schema(role='role_1')) == {'not': s_f.get_schema()}


def test_document_field():
    class B(Document):
        name = Var({
            'response': StringField(required=True),
            'request': StringField(),
        })

    class A(Document):
        id = Var({'response': StringField(required=True)})
        b = DocumentField(B)

    field = DocumentField(A)

    assert list(field.resolve_and_walk()) == [field]

    assert (sorted(field.resolve_and_walk(through_document_fields=True), key=id) ==
            sorted([field, A.b], key=id))

    assert (sorted(field.resolve_and_walk(role='response', through_document_fields=True), key=id) ==
            sorted([
                field,
                A.b,
                A.resolve_field('id', 'response').value,
                B.resolve_field('name', 'response').value,
            ], key=id))

    assert sorted(field.resolve_and_walk(through_document_fields=True, role='request'), key=id) == sorted([
        field,
        A.b,
        B.resolve_field('name', 'request').value,
    ], key=id)


def test_basics():
    class User(Document):
        id = Var({
            'response': IntField(required=True)
        })
        login = StringField(required=True)

    class Task(Document):
        class Options(object):
            title = 'Task'
            description = 'A task.'
            definition_id = 'task'

        id = IntField(required=Var({'response': True}))
        name = StringField(required=True, min_length=5)
        type = StringField(required=True, enum=['TYPE_1', 'TYPE_2'])
        created_at = DateTimeField(required=True)
        author = Var({'response': DocumentField(User)})

    assert normalize(Task.get_schema()) == normalize({
        '$schema': 'http://json-schema.org/draft-04/schema#',
        'additionalProperties': False,
        'description': 'A task.',
        'properties': {
            'created_at': {'format': 'date-time', 'type': 'string'},
            'id': {'type': 'integer'},
            'name': {'minLength': 5, 'type': 'string'},
            'type': {'enum': ['TYPE_1', 'TYPE_2'], 'type': 'string'}
        },
        'required': ['created_at', 'type', 'name'],
        'title': 'Task',
        'type': 'object'
    })

    assert normalize(Task.get_schema(role='response')) == normalize({
        '$schema': 'http://json-schema.org/draft-04/schema#',
        'title': 'Task',
        'description': 'A task.',
        'type': 'object',
        'additionalProperties': False,
        'properties': {
            'created_at': {'format': 'date-time', 'type': 'string'},
            'id': {'type': 'integer'},
            'name': {'minLength': 5, 'type': 'string'},
            'type': {'enum': ['TYPE_1', 'TYPE_2'], 'type': 'string'},
            'author': {
                'additionalProperties': False,
                'properties': {
                    'id': {'type': 'integer'},
                    'login': {'type': 'string'}
                },
                'required': ['id', 'login'],
                'type': 'object'
            },
        },
        'required': ['created_at', 'type', 'name', 'id'],
    })


def test_document():
    class A(Document):
        a = Var({'role_1': DocumentField('self')})

    assert not A.is_recursive()
    assert A.is_recursive(role='role_1')

    class A(Document):
        class Options(object):
            definition_id = Var({'role_1': 'a'})

    assert A.get_definition_id(role='role_1') == 'a'
    assert A.get_definition_id(role='role_2').endswith(A.__name__)
