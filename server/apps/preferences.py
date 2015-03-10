# -*- coding: utf-8; -*-
#
# This file is part of Superdesk.
#
# Copyright 2013, 2014 Sourcefabric z.u. and contributors.
#
# For the full copyright and license information, please see the
# AUTHORS and LICENSE files distributed with this source code, or
# at https://www.sourcefabric.org/superdesk/license

from flask import g, request
from eve.validation import ValidationError

import superdesk
from superdesk.resource import Resource
from superdesk.services import BaseService
from superdesk import get_backend
from superdesk import get_resource_service
from superdesk.workflow import get_privileged_actions


_preferences_key = 'preferences'
_user_preferences_key = 'user_preferences'
_session_preferences_key = 'session_preferences'
_privileges_key = 'active_privileges'
_action_key = 'allowed_actions'


def init_app(app):
    endpoint_name = 'preferences'
    service = PreferencesService(endpoint_name, backend=get_backend())
    PreferencesResource(endpoint_name, app=app, service=service)

    superdesk.intrinsic_privilege(resource_name=endpoint_name, method=['PATCH'])


class PreferencesResource(Resource):
    datasource = {
        'source': 'users',
        'projection': {
            _session_preferences_key: 1,
            _user_preferences_key: 1,
            _privileges_key: 1,
            _action_key: 1
        }
    }
    schema = {
        _session_preferences_key: {'type': 'dict', 'required': True},
        _user_preferences_key: {'type': 'dict', 'required': True},
        _privileges_key: {'type': 'dict'},
        _action_key: {'type': 'list'}
    }
    resource_methods = []
    item_methods = ['GET', 'PATCH']

    superdesk.register_default_user_preference('feature:preview', {
        'type': 'bool',
        'enabled': False,
        'default': False,
        'label': 'Enable Feature Preview',
        'category': 'feature'
    })

    superdesk.register_default_user_preference('archive:view', {
        'type': 'string',
        'allowed': ['mgrid', 'compact'],
        'view': 'mgrid',
        'default': 'mgrid',
        'label': 'Users archive view format',
        'category': 'archive'
    })

    superdesk.register_default_user_preference('editor:theme', {
        'type': 'string',
        'theme': '',
        'label': 'Users article edit screen editor theme',
        'category': 'editor'
    })

    superdesk.register_default_user_preference('workqueue:items', {
        'items': []
    })

    superdesk.register_default_session_preference('scratchpad:items', [])
    superdesk.register_default_session_preference('desk:last_worked', '')
    superdesk.register_default_session_preference('desk:items', [])
    superdesk.register_default_session_preference('stage:items', [])
    superdesk.register_default_session_preference('pinned:items', [])


class PreferencesService(BaseService):

    def set_session_based_prefs(self, session_id, user_id):
        user_doc = get_resource_service('users').find_one(req=None, _id=user_id)
        updates = {}
        if _user_preferences_key not in user_doc:
            orig_user_prefs = user_doc.get(_preferences_key, {})
            available = dict(superdesk.default_user_preferences)
            available.update(orig_user_prefs)
            updates[_user_preferences_key] = available

        session_prefs = user_doc.get(_session_preferences_key, {})
        available = dict(superdesk.default_session_preferences)
        if available.get('desk:last_worked') == '' and user_doc.get('desk'):
            available['desk:last_worked'] = user_doc.get('desk')

        session_prefs.setdefault(str(session_id), available)
        updates[_session_preferences_key] = session_prefs

        self.enhance_document_with_user_privileges(updates)
        updates[_action_key] = get_privileged_actions(updates[_privileges_key])

        self.backend.update(self.datasource, user_id, updates, user_doc)

    def find_one(self, req, **lookup):
        session = get_resource_service('sessions').find_one(req=None, _id=lookup['_id'])
        _id = session['user'] if session else lookup['_id']
        doc = super().find_one(req, _id=_id)
        if doc:
            doc['_id'] = session['_id'] if session else _id
        return doc

    def on_fetched_item(self, doc):
        session_id = request.view_args['_id']
        session_prefs = doc.get(_session_preferences_key, {})[session_id]
        doc[_session_preferences_key] = session_prefs

    def on_update(self, updates, original):
        # Beware, dragons ahead
        existing_user_preferences = original.get(_user_preferences_key, {}).copy()
        existing_session_preferences = original.get(_session_preferences_key, {}).copy()

        user_prefs = updates.get(_user_preferences_key)
        if user_prefs is not None:
            # check if the input is validated against the default values
            for k in ((k for k, v in user_prefs.items() if k not in superdesk.default_user_preferences)):
                raise ValidationError('Invalid preference: %s' % k)

            existing_user_preferences.update(user_prefs)
            updates[_user_preferences_key] = existing_user_preferences

        session_id = request.view_args['_id']
        session_prefs = updates.get(_session_preferences_key)
        if session_prefs is not None:
            for k in ((k for k, v in session_prefs.items() if k not in superdesk.default_session_preferences)):
                raise ValidationError('Invalid preference: %s' % k)

            existing_session_preferences[session_id].update(session_prefs)
            updates[_session_preferences_key] = existing_session_preferences

        self.enhance_document_with_user_privileges(updates)
        updates[_action_key] = get_privileged_actions(updates[_privileges_key])

    def update(self, id, updates, original):
        session = get_resource_service('sessions').find_one(req=None, _id=original['_id'])
        original = self.backend.find_one(self.datasource, req=None, _id=session['user'])
        return self.backend.update(self.datasource, original['_id'], updates, original)

    def enhance_document_with_default_prefs(self, session_doc, user_doc):
        orig_user_prefs = user_doc.get(_preferences_key, {})
        available = dict(superdesk.default_user_preferences)
        available.update(orig_user_prefs)
        session_doc[_user_preferences_key] = available

        orig_session_prefs = session_doc.get(_session_preferences_key, {})
        available = dict(superdesk.default_session_preferences)
        available.update(orig_session_prefs)

        if available.get('desk:last_worked') == '' and user_doc.get('desk'):
            available['desk:last_worked'] = user_doc.get('desk')

        session_doc[_session_preferences_key] = available

    def enhance_document_with_user_privileges(self, user_doc):
        role_doc = get_resource_service('users').get_role(user_doc)
        get_resource_service('users').set_privileges(user_doc, role_doc)

    def get_user_preference(self, user_id):
        """
        This function returns preferences for the user.
        """
        doc = get_resource_service('users').find_one(req=None, _id=user_id)
        self.enhance_document_with_default_user_prefs(user_doc=doc)
        prefs = doc.get(_user_preferences_key, {})
        return prefs

    def email_notification_is_enabled(self, user_id=None, preferences=None):
        """
        This function checks if email notification is enabled or not based on the preferences.
        """
        if user_id:
            preferences = self.get_user_preference(user_id)
        send_email = preferences.get('email:notification', {}) if isinstance(preferences, dict) else {}
        return send_email and send_email.get('enabled', False)

    def is_authorized(self, **kwargs):
        """
        Returns False if logged-in user is trying to update other user's or session's privileges.

        :param kwargs:
        :return: True if authorized, False otherwise
        """

        if kwargs.get("user_id") is None:
            return False

        session = get_resource_service('sessions').find_one(req=None, _id=kwargs.get('user_id'))
        authorized = str(g.user['_id']) == str(session.get("user"))
        return authorized
