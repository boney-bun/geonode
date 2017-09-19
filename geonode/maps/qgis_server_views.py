# -*- coding: utf-8 -*-
#########################################################################
#
# Copyright (C) 2016 OSGeo
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program. If not, see <http://www.gnu.org/licenses/>.
#
#########################################################################
import json

from django.conf import settings
from django.views.generic import CreateView, DetailView, UpdateView

from geonode.maps.views import _resolve_map, _PERMISSION_MSG_VIEW, \
    snapshot_config

from geonode.maps.models import Map, MapLayer
from geonode.layers.models import Layer


class MapCreateView(CreateView):
    model = Map
    fields = '__all__'
    template_name = 'leaflet_maps/map_view.html'
    context_object_name = 'map'

    def get_context_data(self, **kwargs):
        # list all required layers
        layers = Layer.objects.all()
        context = {
            'create': True,
            'layers': layers
        }
        return context

    def get_success_url(self):
        pass

    def get_form_kwargs(self):
        kwargs = super(MapCreateView, self).get_form_kwargs()
        return kwargs


class MapDetailView(DetailView):
    model = Map
    template_name = 'leaflet_maps/map_view.html'
    context_object_name = 'map'

    def get_context_data(self, **kwargs):
        """Prepare context data."""

        mapid = self.kwargs.get('mapid')
        snapshot = self.kwargs.get('snapshot')
        request = self.request

        map_obj = _resolve_map(
            request, mapid, 'base.view_resourcebase', _PERMISSION_MSG_VIEW)

        if 'access_token' in request.session:
            access_token = request.session['access_token']
        else:
            access_token = None

        if snapshot is None:
            config = map_obj.viewer_json(request.user, access_token)
        else:
            config = snapshot_config(snapshot, map_obj, request.user,
                                     access_token)
        # list all required layers
        layers = Layer.objects.all()
        map_layers = MapLayer.objects.filter(
            map_id=mapid).order_by('stack_order')
        context = {
            'config': json.dumps(config),
            'create': False,
            'layers': layers,
            'map': map_obj,
            'map_layers': map_layers,
            'preview': getattr(
                settings,
                'LAYER_PREVIEW_LIBRARY',
                '')
        }
        return context

    def get_object(self):
        return Map.objects.get(id=self.kwargs.get("mapid"))


class MapEmbedView(DetailView):
        model = Map
        template_name = 'leaflet_maps/map_detail.html'
        context_object_name = 'map'

        def get_context_data(self, **kwargs):
            """Prepare context data."""

            mapid = self.kwargs.get('mapid')
            snapshot = self.kwargs.get('snapshot')
            request = self.request

            map_obj = _resolve_map(
                request, mapid, 'base.view_resourcebase', _PERMISSION_MSG_VIEW)

            if 'access_token' in request.session:
                access_token = request.session['access_token']
            else:
                access_token = None

            if snapshot is None:
                config = map_obj.viewer_json(request.user, access_token)
            else:
                config = snapshot_config(snapshot, map_obj, request.user,
                                         access_token)
            # list all required layers
            layers = Layer.objects.all()
            map_layers = MapLayer.objects.filter(
                map_id=mapid).order_by('stack_order')
            context = {
                'config': json.dumps(config),
                'create': False,
                'layers': layers,
                'resource': map_obj,
                'map_layers': map_layers,
                'preview': getattr(
                    settings,
                    'LAYER_PREVIEW_LIBRARY',
                    '')
            }
            return context

        def get_object(self):
            return Map.objects.get(id=self.kwargs.get("mapid"))


class MapEditView(UpdateView):
    model = Map
    fields = '__all__'
    template_name = 'leaflet_maps/map_edit.html'
    context_object_name = 'map'

    def get_context_data(self, **kwargs):
        # list all required layers
        mapid = self.kwargs.get('mapid')
        snapshot = self.kwargs.get('snapshot')
        request = self.request
        map_obj = _resolve_map(request,
                               mapid,
                               'base.view_resourcebase',
                               _PERMISSION_MSG_VIEW)

        if 'access_token' in request.session:
            access_token = request.session['access_token']
        else:
            access_token = None

        if snapshot is None:
            config = map_obj.viewer_json(request.user,
                                         access_token)
        else:
            config = snapshot_config(snapshot,
                                     map_obj,
                                     request.user,
                                     access_token)

        layers = Layer.objects.all()
        map_layers = MapLayer.objects.filter(
            map_id=mapid).order_by('stack_order')

        context = {
            'create': False,
            'config': json.dumps(config),
            'layers': layers,
            'map_layers': map_layers,
            'map': map_obj,
            'preview': getattr(
                settings,
                'LAYER_PREVIEW_LIBRARY',
                '')
        }
        return context

    def get(self, request, **kwargs):
        self.object = Map.objects.get(
            id=self.kwargs.get('mapid'))
        form_class = self.get_form_class()
        form = self.get_form(form_class)
        context = self.get_context_data(
            object=self.object, form=form)
        return self.render_to_response(context)

    def get_success_url(self):
        pass

    def get_form_kwargs(self):
        kwargs = super(MapEditView, self).get_form_kwargs()
        return kwargs


class MapUpdateView(UpdateView):
    model = Map
    fields = '__all__'
    template_name = 'leaflet_maps/map_edit.html'
    context_object_name = 'map'

    def get_context_data(self, **kwargs):
        mapid = self.kwargs.get('mapid')
        request = self.request
        map_obj = _resolve_map(request,
                               mapid,
                               'base.view_resourcebase',
                               _PERMISSION_MSG_VIEW)

        if 'access_token' in request.session:
            access_token = request.session['access_token']
        else:
            access_token = None

        if request.method == 'POST':
            if not request.user.is_authenticated():
                return self.render_to_response(
                    'You must be logged in to save new maps',
                    content_type="text/plain",
                    status=401
                )

            map_obj.save()
            map_obj.set_default_permissions()
            map_obj.handle_moderated_uploads()
            # If the body has been read already, use an empty string.
            # See https://github.com/django/django/commit/58d555caf527d6f1bdfeab14527484e4cca68648
            # for a better exception to catch when we move to Django 1.7.
            try:
                body = request.body
            except Exception:
                body = ''

            try:
                map_obj.update_from_viewer(body)
            except ValueError as e:
                return self.render_to_response(str(e), status=400)
            else:
                context = {
                    'create': False,
                    'status': 200,
                    'map': map_obj,
                    'content_type': 'application/json'
                }
                return context
        else:
            return self.render_to_response(status=405)

    def get(self, request, **kwargs):
        self.object = Map.objects.get(
            id=self.kwargs.get('mapid'))
        form_class = self.get_form_class()
        form = self.get_form(form_class)
        context = self.get_context_data(object=self.object,
                                        form=form)
        return self.render_to_response(context)

    def get_object(self, queryset=None):
        obj = Map.objects.get(
            id=self.kwargs.get('mapid'))
        return obj
