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

import os
import shutil
import json
import datetime
import tempfile
import unittest
import urllib2
# import base64
import time
import logging
import gisdata

from django.conf import settings
from django.core.exceptions import ObjectDoesNotExist
from django.core.management import call_command
from django.contrib.auth.models import Group, Permission
from django.test import LiveServerTestCase as TestCase
from django.core.urlresolvers import reverse
from django.contrib.staticfiles.templatetags import staticfiles
from django.contrib.auth import get_user_model
from guardian.shortcuts import get_anonymous_user, assign_perm, remove_perm

from geonode.base.populate_test_data import create_models
from geoserver.catalog import FailedRequestError, UploadError

# from geonode.security.models import *
from geonode.layers.models import Layer
from geonode.layers.utils import layer_type, get_files, get_valid_name, \
    get_valid_layer_name
from geonode.maps.models import Map, MapLayer
from geonode.maps.tests_populate_maplayers import create_maplayers
from geonode.people.models import Profile
from geonode.utils import default_map_config
from geonode import GeoNodeException
from geonode.layers.utils import (
    upload,
    file_upload,
)
from geonode.tests.utils import check_layer, get_web_page

from geonode.geoserver.helpers import cascading_delete, set_attributes_from_geoserver
# FIXME(Ariel): Uncomment these when #1767 is fixed
# from geonode.geoserver.helpers import get_time_info
# from geonode.geoserver.helpers import get_wms
# from geonode.geoserver.helpers import set_time_info
from geonode.geoserver.signals import gs_catalog
from guardian.shortcuts import get_anonymous_user, assign_perm, remove_perm

LOGIN_URL = "/accounts/login/"

logging.getLogger("south").setLevel(logging.INFO)

"""
 HOW TO RUN THE TESTS
 --------------------
 (https://github.com/GeoNode/geonode/blob/master/docs/tutorials/devel/testing.txt)

 1)
  (https://github.com/GeoNode/geonode/blob/master/docs/tutorials/devel/envsetup/paver.txt)

  $ paver setup

   1a. If using a PostgreSQL DB
       $ sudo su postgres
       $ psql
       ..>  ALTER USER test_geonode CREATEDB;
       ..>  ALTER USER test_geonode WITH SUPERUSER;
       ..>  \q
       $ exit

2)

  $ paver test_integration > tests_integration.log 2>&1

  2a)

    $ paver test_integration -n geonode.tests.integration:GeoNodeMapTest.test_cascading_delete

A. Create a GeoNode DB (If using a PostgreSQL DB)

$ sudo su postgres
$ psql -c "drop database test_geonode;"
$ createuser -P test_geonode
  pw: geonode
$ createdb -O test_geonode test_geonode
$ psql -d test_geonode -c "create extension postgis;"
$ psql -d test_geonode -c "grant all on spatial_ref_sys to public;"
$ psql -d test_geonode -c "grant all on geometry_columns to public;"
$ exit

$ geonode migrate
$ geonode createsuperuser

"""


def fix_baselayers(map_id):
    """
    Fix base layers for a given map.
    """

    try:
        id = int(map_id)
    except ValueError:
        print 'map_id must be an integer'
        return

    if not Map.objects.filter(pk=id).exists():
        print 'There is not a map with id %s' % id
        return

    map = Map.objects.get(pk=id)
    # first we delete all of the base layers
    map.layer_set.filter(local=False).delete()

    # now we re-add them
    source = 0
    for base_layer in settings.MAP_BASELAYERS:
        if 'group' in base_layer:
            # layer_params
            layer_params = {}
            layer_params['selected'] = True
            if 'title' in base_layer:
                layer_params['title'] = base_layer['title']
            if 'type' in base_layer:
                layer_params['type'] = base_layer['type']
            if 'args' in base_layer:
                layer_params['args'] = base_layer['args']
            # source_params
            source_params = {}
            source_params['id'] = source
            for param in base_layer['source']:
                source_params[param] = base_layer['source'][param]
            # let's create the map layer
            name = ''
            if 'name' in base_layer:
                name = base_layer['name']
            else:
                if 'args' in base_layer:
                    name = base_layer['args'][0]
            map_layer = MapLayer(
                map=map,
                stack_order=map.layer_set.count() + 1,
                name=name,
                opacity=1,
                transparent=False,
                fixed=True,
                group='background',
                layer_params=json.dumps(layer_params),
                source_params=json.dumps(source_params)
            )
            map_layer.save()
        source += 1



class GeoNodeCoreTest(TestCase):

    """Tests geonode.security app/module
    """

    def setUp(self):
        pass

    def tearDown(self):
        pass


class GeoNodeProxyTest(TestCase):

    """Tests geonode.proxy app/module
    """

    def setUp(self):
        pass

    def tearDown(self):
        pass


class NormalUserTest(TestCase):

    """
    Tests GeoNode functionality for non-administrative users
    """

    def setUp(self):
        call_command('loaddata', 'people_data', verbosity=0)

    def tearDown(self):
        pass

    def test_layer_upload(self):
        """ Try uploading a layer and verify that the user can administrate
        his own layer despite not being a site administrator.
        """

        self.client.login(username='norman', password='norman')

        # TODO: Would be nice to ensure the name is available before
        # running the test...
        norman = get_user_model().objects.get(username="norman")
        saved_layer = file_upload(
            os.path.join(
                gisdata.VECTOR_DATA,
                "san_andres_y_providencia_poi.shp"),
            name="san_andres_y_providencia_poi_by_norman",
            user=norman,
            overwrite=True,
        )
        saved_layer.set_default_permissions()
        url = reverse('layer_metadata', args=[saved_layer.service_typename])
        resp = self.client.get(url)
        self.assertEquals(resp.status_code, 200)


class GeoNodeMapTest(TestCase):

    """Tests geonode.maps app/module
    """

    def setUp(self):
        call_command('loaddata', 'people_data', verbosity=0)

    def tearDown(self):
        pass

    # geonode.maps.utils


    @unittest.skipIf(
        hasattr(settings, 'SKIP_GEOSERVER_TEST') and
        settings.SKIP_GEOSERVER_TEST,
        'Temporarily skip this test until fixed')
    def test_raster_upload(self):
        """Test that the wcs links are correctly created for a raster"""
        filename = os.path.join(gisdata.GOOD_DATA, 'raster/test_grid.tif')
        uploaded = file_upload(filename)
        wcs_link = False
        for link in uploaded.link_set.all():
            if link.mime == 'image/tif':
                wcs_link = True
        self.assertTrue(wcs_link)

    def test_layer_upload(self):
        """Test that layers can be uploaded to running GeoNode/GeoServer
        """
        layers = {}
        expected_layers = []
        not_expected_layers = []

        for filename in os.listdir(gisdata.GOOD_DATA):
            basename, extension = os.path.splitext(filename)
            if extension.lower() in ['.tif', '.shp', '.zip']:
                expected_layers.append(
                    os.path.join(
                        gisdata.GOOD_DATA,
                        filename))

        for filename in os.listdir(gisdata.BAD_DATA):
            not_expected_layers.append(
                os.path.join(gisdata.BAD_DATA, filename)
            )
        uploaded = upload(gisdata.DATA_DIR, console=None)

        for item in uploaded:
            errors = 'error' in item
            if errors:
                # should this file have been uploaded?
                if item['file'] in not_expected_layers:
                    continue
                else:
                    msg = ('Could not upload file "%s", '
                           'and it is not in %s' % (
                               item['file'], not_expected_layers))
                    assert errors, msg
            else:
                msg = ('Upload should have returned either "name" or '
                       '"errors" for file %s.' % item['file'])
                assert 'name' in item, msg
                layers[item['file']] = item['name']

        msg = ('There were %s compatible layers in the directory,'
               ' but only %s were sucessfully uploaded' %
               (len(expected_layers), len(layers)))
        # assert len(layers) == len(expected_layers), msg

        for layer in expected_layers:
            msg = ('The following file should have been uploaded'
                   'but was not: %s. ' % layer)
            assert layer in layers, msg

            layer_name = layers[layer]

            # Check the layer is in the Django database
            Layer.objects.get(name=layer_name)

            # Check that layer is in geoserver
            found = False
            gs_username, gs_password = settings.OGC_SERVER['default'][
                'USER'], settings.OGC_SERVER['default']['PASSWORD']
            page = get_web_page(
                os.path.join(
                    settings.OGC_SERVER['default']['LOCATION'],
                    'rest/layers'),
                username=gs_username,
                password=gs_password)
            if page.find('rest/layers/%s.html' % layer_name) > 0:
                found = True
            if not found:
                msg = (
                    'Upload could not be verified, the layer %s is not '
                    'in geoserver %s, but GeoNode did not raise any errors, '
                    'this should never happen.' %
                    (layer_name, settings.OGC_SERVER['default']['LOCATION']))
                raise GeoNodeException(msg)

        # server_url = settings.OGC_SERVER['default']['LOCATION'] + 'ows?'
        # Verify that the GeoServer GetCapabilities record is accessible:
        # metadata = get_layers_metadata(server_url, '1.0.0')
        # msg = ('The metadata list should not be empty in server %s'
        #        % server_url)
        # assert len(metadata) > 0, msg
        # Check the keywords are recognized too

        # Clean up and completely delete the layers
        for layer in expected_layers:
            layer_name = layers[layer]
            Layer.objects.get(name=layer_name).delete()

    def test_extension_not_implemented(self):
        """Verify a GeoNodeException is returned for not compatible extensions
        """
        sampletxt = os.path.join(gisdata.VECTOR_DATA,
                                 'points_epsg2249_no_prj.dbf')
        try:
            file_upload(sampletxt)
        except GeoNodeException:
            pass
        except Exception:
            raise
            # msg = ('Was expecting a %s, got %s instead.' %
            #        (GeoNodeException, type(e)))
            # assert e is GeoNodeException, msg

    @unittest.skipIf(
        hasattr(settings, 'SKIP_GEOSERVER_TEST') and
        settings.SKIP_GEOSERVER_TEST,
        'Temporarily skip this test until fixed')
    def test_fix_baselayers(self):
        """Test fix_baselayers function, used by the fix_baselayers command
        """
        map_id = 1
        map_obj = Map.objects.get(id=map_id)

        # number of base layers (we remove the local geoserver entry from the total)
        n_baselayers = len(settings.MAP_BASELAYERS) - 1

        # number of local layers
        n_locallayers = map_obj.layer_set.filter(local=True).count()

        fix_baselayers(map_id)

        self.assertEquals(map_obj.layer_set.all().count(), n_baselayers + n_locallayers)

    def test_layer_upload_metadata(self):
        """Test uploading a layer with XML metadata"""

        thelayer = os.path.join(
            gisdata.PROJECT_ROOT,
            'both',
            'good',
            'sangis.org',
            'Airport',
            'Air_Runways.shp')

        self.assertTrue('%s.xml' % thelayer,
                        'Expected layer XML metadata to exist')

        uploaded = file_upload(thelayer, overwrite=True)

        self.assertEqual(
            uploaded.title,
            'Air_Runways',
            'Expected specific title from uploaded layer XML metadata')

        self.assertEqual(
            uploaded.abstract,
            'Airport Runways',
            'Expected specific abstract from uploaded layer XML metadata')

        self.assertEqual(
            uploaded.purpose,
            'To show the location of Public Airports '
            'and Runways within San Diego County',
            'Expected specific purpose from uploaded layer XML metadata')

        self.assertEqual(uploaded.supplemental_information,
                         'No information provided',
                         'Expected specific supplemental information '
                         'from uploaded layer XML metadata')

        self.assertEqual(len(uploaded.keyword_list(
        )), 5, 'Expected specific number of keywords from uploaded layer XML metadata')

        self.assertEqual(uploaded.keyword_csv,
                         u'Airport,Airports,Landing Strips,Runway,Runways',
                         'Expected CSV of keywords from uploaded layer XML metadata')

        self.assertTrue(
            'Landing Strips' in uploaded.keyword_list(),
            'Expected specific keyword from uploaded layer XML metadata')

        self.assertEqual(
            uploaded.constraints_other,
            'None',
            'Expected specific constraint from uploaded layer XML metadata')

        self.assertEqual(
            uploaded.date,
            datetime.datetime(
                2010,
                8,
                3,
                0,
                0),
            'Expected specific date from uploaded layer XML metadata')

        # Clean up and completely delete the layer
        uploaded.delete()

    def test_shapefile(self):
        """Test Uploading a good shapefile
        """
        thefile = os.path.join(
            gisdata.VECTOR_DATA,
            'san_andres_y_providencia_poi.shp')
        uploaded = file_upload(thefile, overwrite=True)
        check_layer(uploaded)

        # Clean up and completely delete the layer
        uploaded.delete()

    def test_bad_shapefile(self):
        """Verifying GeoNode complains about a shapefile without .prj
        """

        thefile = os.path.join(gisdata.BAD_DATA, 'points_epsg2249_no_prj.shp')
        try:
            file_upload(thefile, overwrite=True)
        except UploadError:
            pass
        except GeoNodeException:
            pass
        except Exception:
            raise
            # msg = ('Was expecting a %s, got %s instead.' %
            #        (GeoNodeException, type(e)))
            # assert e is GeoNodeException, msg

    def test_tiff(self):
        """Uploading a good .tiff
        """
        thefile = os.path.join(gisdata.RASTER_DATA, 'test_grid.tif')
        uploaded = file_upload(thefile, overwrite=True)
        check_layer(uploaded)

        # Clean up and completely delete the layer
        uploaded.delete()

    def test_repeated_upload(self):
        """Upload the same file more than once
        """
        thefile = os.path.join(gisdata.RASTER_DATA, 'test_grid.tif')
        uploaded1 = file_upload(thefile, overwrite=True)
        check_layer(uploaded1)
        uploaded2 = file_upload(thefile, overwrite=True)
        check_layer(uploaded2)
        uploaded3 = file_upload(thefile, overwrite=False)
        check_layer(uploaded3)
        msg = ('Expected %s but got %s' % (uploaded1.name, uploaded2.name))
        assert uploaded1.name == uploaded2.name, msg
        msg = ('Expected a different name when uploading %s using '
               'overwrite=False but got %s' % (thefile, uploaded3.name))
        assert uploaded1.name != uploaded3.name, msg

        # Clean up and completely delete the layers

        # uploaded1 is overwritten by uploaded2 ... no need to delete it
        uploaded2.delete()
        uploaded3.delete()

    # geonode.maps.views

    @unittest.skipIf(
        hasattr(settings, 'SKIP_GEOSERVER_TEST') and
        settings.SKIP_GEOSERVER_TEST,
        'Temporarily skip this test until fixed')
    def test_layer_delete_from_geoserver(self):
        """Verify that layer is correctly deleted from GeoServer
        """
        # Layer.delete() calls the pre_delete hook which uses cascading_delete()
        # Should we explicitly test that the styles and store are
        # deleted as well as the resource itself?
        # There is already an explicit test for cascading delete

        gs_cat = gs_catalog

        # Test Uploading then Deleting a Shapefile from GeoServer
        shp_file = os.path.join(
            gisdata.VECTOR_DATA,
            'san_andres_y_providencia_poi.shp')
        shp_layer = file_upload(shp_file, overwrite=True)
        ws = gs_cat.get_workspace(shp_layer.workspace)
        shp_store = gs_cat.get_store(shp_layer.store, ws)
        shp_store_name = shp_store.name
        shp_layer.delete()
        # self.assertIsNone(gs_cat.get_resource(shp_layer.name, store=shp_store))
        self.assertRaises(
            FailedRequestError,
            lambda: gs_cat.get_store(shp_store_name))

        # Test Uploading then Deleting a TIFF file from GeoServer
        tif_file = os.path.join(gisdata.RASTER_DATA, 'test_grid.tif')
        tif_layer = file_upload(tif_file)
        ws = gs_cat.get_workspace(tif_layer.workspace)
        tif_store = gs_cat.get_store(tif_layer.store, ws)
        tif_layer.delete()
        self.assertRaises(
            FailedRequestError,
            lambda: gs_cat.get_resource(
                shp_layer.name,
                store=tif_store))

    @unittest.skipIf(
        hasattr(settings, 'SKIP_GEOSERVER_TEST') and
        settings.SKIP_GEOSERVER_TEST,
        'Temporarily skip this test until fixed')
    def test_delete_layer(self):
        """Verify that the 'delete_layer' pre_delete hook is functioning
        """

        gs_cat = gs_catalog

        # Upload a Shapefile Layer
        shp_file = os.path.join(
            gisdata.VECTOR_DATA,
            'san_andres_y_providencia_poi.shp')
        shp_layer = file_upload(shp_file)
        shp_layer_id = shp_layer.pk
        ws = gs_cat.get_workspace(shp_layer.workspace)
        shp_store = gs_cat.get_store(shp_layer.store, ws)
        shp_store_name = shp_store.name

        uuid = shp_layer.uuid

        # Delete it with the Layer.delete() method
        shp_layer.delete()

        # Verify that it no longer exists in GeoServer
        # self.assertIsNone(gs_cat.get_resource(name, store=shp_store))
        # self.assertIsNone(gs_cat.get_layer(shp_layer.name))
        self.assertRaises(
            FailedRequestError,
            lambda: gs_cat.get_store(shp_store_name))

        # Check that it was also deleted from GeoNodes DB
        self.assertRaises(ObjectDoesNotExist,
                          lambda: Layer.objects.get(pk=shp_layer_id))

    # geonode.geoserver.helpers
        # If catalogue is installed, then check that it is deleted from there
        # too.
        if 'geonode.catalogue' in settings.INSTALLED_APPS:
            from geonode.catalogue import get_catalogue
            catalogue = get_catalogue()

            # Verify that it no longer exists in GeoNetwork
            shp_layer_gn_info = catalogue.get_record(uuid)
            assert shp_layer_gn_info is None

    @unittest.skipIf(
        hasattr(settings, 'SKIP_GEOSERVER_TEST') and
        settings.SKIP_GEOSERVER_TEST,
        'Temporarily skip this test until fixed')
    def test_cascading_delete(self):
        """Verify that the helpers.cascading_delete() method is working properly
        """
        gs_cat = gs_catalog

        # Upload a Shapefile
        shp_file = os.path.join(
            gisdata.VECTOR_DATA,
            'san_andres_y_providencia_poi.shp')
        shp_layer = file_upload(shp_file)

        # Save the names of the Resource/Store/Styles
        resource_name = shp_layer.name
        ws = gs_cat.get_workspace(shp_layer.workspace)
        store = gs_cat.get_store(shp_layer.store, ws)
        store_name = store.name
        layer = gs_cat.get_layer(resource_name)
        styles = layer.styles + [layer.default_style]

        # Delete the Layer using cascading_delete()
        cascading_delete(gs_cat, shp_layer.typename)

        # Verify that the styles were deleted
        for style in styles:
            s = gs_cat.get_style(style.name)
            assert s is None

        # Verify that the resource was deleted
        self.assertRaises(
            FailedRequestError,
            lambda: gs_cat.get_resource(
                resource_name,
                store=store))

        # Verify that the store was deleted
        self.assertRaises(
            FailedRequestError,
            lambda: gs_cat.get_store(store_name))

        # Clean up by deleting the layer from GeoNode's DB and GeoNetwork
        shp_layer.delete()

    def test_keywords_upload(self):
        """Check that keywords can be passed to file_upload
        """
        thefile = os.path.join(
            gisdata.VECTOR_DATA,
            'san_andres_y_providencia_poi.shp')
        uploaded = file_upload(
            thefile,
            keywords=[
                'foo',
                'bar'],
            overwrite=True)
        keywords = uploaded.keyword_list()
        msg = 'No keywords found in layer %s' % uploaded.name
        assert len(keywords) > 0, msg
        assert 'foo' in uploaded.keyword_list(
        ), 'Could not find "foo" in %s' % keywords
        assert 'bar' in uploaded.keyword_list(
        ), 'Could not find "bar" in %s' % keywords

    def test_empty_bbox(self):
        """Regression-test for failures caused by zero-width bounding boxes"""
        thefile = os.path.join(gisdata.VECTOR_DATA, 'single_point.shp')
        uploaded = file_upload(thefile, overwrite=True)
        uploaded.set_default_permissions()
        self.client.login(username='norman', password='norman')
        resp = self.client.get(uploaded.get_absolute_url())
        self.assertEquals(resp.status_code, 200)

    # The replace functionality has not worked yet
    def test_layer_replace(self):
        """Test layer replace functionality
        """
        vector_file = os.path.join(
            gisdata.VECTOR_DATA,
            'san_andres_y_providencia_administrative.shp')
        vector_layer = file_upload(vector_file, overwrite=True)

        raster_file = os.path.join(gisdata.RASTER_DATA, 'test_grid.tif')
        raster_layer = file_upload(raster_file, overwrite=True)

        self.client.login(username='admin', password='admin')

        # test the program can determine the original layer in raster type
        raster_replace_url = reverse(
            'layer_replace', args=[
                raster_layer.service_typename])
        response = self.client.get(raster_replace_url)
        self.assertEquals(response.status_code, 200)
        self.assertEquals(response.context['is_featuretype'], False)

        # test the program can determine the original layer in vector type
        vector_replace_url = reverse(
            'layer_replace', args=[
                vector_layer.service_typename])
        response = self.client.get(vector_replace_url)
        self.assertEquals(response.status_code, 200)
        self.assertEquals(response.context['is_featuretype'], True)

        # test replace a vector with a raster
        response = self.client.post(
            vector_replace_url, {
                'base_file': open(
                    raster_file, 'rb')})
        # TODO: This should really return a 400 series error with the json dict
        self.assertEquals(response.status_code, 400)
        response_dict = json.loads(response.content)
        self.assertEquals(response_dict['success'], False)

        # test replace a vector with a different vector
        new_vector_file = os.path.join(
            gisdata.VECTOR_DATA,
            'san_andres_y_providencia_poi.shp')
        layer_path, __ = os.path.splitext(new_vector_file)
        layer_base = open(layer_path + '.shp', 'rb')
        layer_dbf = open(layer_path + '.dbf', 'rb')
        layer_shx = open(layer_path + '.shx', 'rb')
        layer_prj = open(layer_path + '.prj', 'rb')

        response = self.client.post(
            vector_replace_url,
            {'base_file': layer_base,
             'dbf_file': layer_dbf,
             'shx_file': layer_shx,
             'prj_file': layer_prj
             })
        # the functionality has not worked properly.
        # set to 400 instead
        # self.assertEquals(response.status_code, 200)
        # the functionality not working yet, status_code is 400
        self.assertEquals(response.status_code, 400)
        response_dict = json.loads(response.content)
        # self.assertEquals(response_dict['success'], True)
        # failed to get a success response.
        # set to false.
        self.assertEquals(response_dict['success'], False)

        # Get a Layer object for the newly created layer.
        new_vector_layer = Layer.objects.get(pk=vector_layer.pk)
        # FIXME(Ariel): Check the typename does not change.

        # Test the replaced layer is indeed different from the original layer
        self.assertNotEqual(vector_layer.bbox_x0, new_vector_layer.bbox_x0)
        self.assertNotEqual(vector_layer.bbox_x1, new_vector_layer.bbox_x1)
        self.assertNotEqual(vector_layer.bbox_y0, new_vector_layer.bbox_y0)
        self.assertNotEqual(vector_layer.bbox_y1, new_vector_layer.bbox_y1)

        # test an invalid user without layer replace permission
        self.client.logout()
        self.client.login(username='norman', password='norman')

        response = self.client.post(
            vector_replace_url,
            {'base_file': layer_base,
             'dbf_file': layer_dbf,
             'shx_file': layer_shx,
             'prj_file': layer_prj
             })
        # 401 is Unauthorized
        #self.assertEquals(response.status_code, 401)
        # return forbidden error  (403)
        self.assertEquals(response.status_code, 403)

    @unittest.skipIf(
        hasattr(settings, 'SKIP_GEOSERVER_TEST') and
        settings.SKIP_GEOSERVER_TEST,
        'Temporarily skip this test until fixed')
    def test_map_view(self):
        """Test that map view can be properly rendered
        """
        # first create a map

        # Test successful new map creation
        self.client.login(username=self.user, password=self.passwd)

        new_map = reverse('new_map_json')
        response = self.client.post(
            new_map,
            data=self.viewer_config,
            content_type="text/json")
        self.assertEquals(response.status_code, 200)
        map_id = int(json.loads(response.content)['id'])
        self.client.logout()

        url = reverse('map_view', args=(map_id,))

        # test unauthenticated user to view map
        response = self.client.get(url)
        self.assertEquals(response.status_code, 200)
        # TODO: unauthenticated user can still access the map view

        # test a user without map view permission
        self.client.login(username='norman', password='norman')
        response = self.client.get(url)
        self.assertEquals(response.status_code, 200)
        self.client.logout()
        # TODO: the user can still access the map view without permission

        # Now test with a valid user using GET method
        self.client.login(username=self.user, password=self.passwd)
        response = self.client.get(url)
        self.assertEquals(response.status_code, 200)

        # Config equals to that of the map whose id is given
        map_obj = Map.objects.get(id=map_id)
        config_map = map_obj.viewer_json(None, None)
        response_config_dict = json.loads(response.context['config'])
        self.assertEquals(
            config_map['about']['abstract'],
            response_config_dict['about']['abstract'])
        self.assertEquals(
            config_map['about']['title'],
            response_config_dict['about']['title'])

    @unittest.skipIf(
        hasattr(settings, 'SKIP_GEOSERVER_TEST') and
        settings.SKIP_GEOSERVER_TEST,
        'Temporarily skip this test until fixed')
    def test_new_map_config(self):
        """Test that new map config can be properly assigned
        """
        self.client.login(username='admin', password='admin')

        # Test successful new map creation
        m = Map()
        admin_user = get_user_model().objects.get(username='admin')
        layer_name = Layer.objects.all()[0].typename
        m.create_from_layer_list(admin_user, [layer_name], "title", "abstract")
        map_id = m.id

        url = reverse('new_map_json')

        # Test GET method with COPY
        response = self.client.get(url, {'copy': map_id})
        self.assertEquals(response.status_code, 200)
        map_obj = Map.objects.get(id=map_id)
        config_map = map_obj.viewer_json(None, None)
        response_config_dict = json.loads(response.content)
        self.assertEquals(
            config_map['map']['layers'],
            response_config_dict['map']['layers'])

        # Test GET method no COPY and no layer in params
        response = self.client.get(url)
        self.assertEquals(response.status_code, 200)
        config_default = default_map_config(None)[0]
        response_config_dict = json.loads(response.content)
        self.assertEquals(
            config_default['about']['abstract'],
            response_config_dict['about']['abstract'])
        self.assertEquals(
            config_default['about']['title'],
            response_config_dict['about']['title'])

        # Test GET method no COPY but with layer in params
        response = self.client.get(url, {'layer': layer_name})
        self.assertEquals(response.status_code, 200)
        response_dict = json.loads(response.content)
        self.assertEquals(response_dict['fromLayer'], True)

        # Test POST method without authentication
        self.client.logout()
        response = self.client.post(url, {'layer': layer_name})
        self.assertEquals(response.status_code, 401)

        # Test POST method with authentication and a layer in params
        self.client.login(username='admin', password='admin')

        response = self.client.post(url, {'layer': layer_name})
        # Should not accept the request
        self.assertEquals(response.status_code, 400)

        # Test POST method with map data in json format
        response = self.client.post(
            url,
            data=self.viewer_config,
            content_type="text/json")
        self.assertEquals(response.status_code, 200)
        map_id = int(json.loads(response.content)['id'])

        # Test methods other than GET or POST and no layer in params
        response = self.client.put(url)
        self.assertEquals(response.status_code, 405)


class GeoNodePermissionsTest(TestCase):

    """Tests GeoNode permissions and its integration with GeoServer
    """

    def setUp(self):
        call_command('loaddata', 'people_data', verbosity=0)

    def tearDown(self):
        pass

    @unittest.skipIf(
        hasattr(settings, 'SKIP_GEOSERVER_TEST') and
        settings.SKIP_GEOSERVER_TEST,
        'Temporarily skip this test until fixed')
    def test_anonymus_permissions(self):

        # grab a layer
        layer = Layer.objects.all()[0]
        layer.set_default_permissions()
        # 1. view_resourcebase
        # 1.1 has view_resourcebase: verify that anonymous user can access
        # the layer detail page
        self.assertTrue(
            self.anonymous_user.has_perm(
                'view_resourcebase',
                layer.get_self_resource()))
        response = self.client.get(reverse('layer_detail', args=(layer.typename,)))
        self.assertEquals(response.status_code, 200)
        # 1.2 has not view_resourcebase: verify that anonymous user can not
        # access the layer detail page
        remove_perm('view_resourcebase', self.anonymous_user, layer.get_self_resource())
        anonymous_group = Group.objects.get(name='anonymous')
        remove_perm('view_resourcebase', anonymous_group, layer.get_self_resource())
        response = self.client.get(reverse('layer_detail', args=(layer.typename,)))
        self.assertEquals(response.status_code, 302)

        # 2. change_resourcebase
        # 2.1 has not change_resourcebase: verify that anonymous user cannot
        # access the layer replace page but redirected to login
        response = self.client.get(reverse('layer_replace', args=(layer.typename,)))
        self.assertEquals(response.status_code, 302)

        # 3. delete_resourcebase
        # 3.1 has not delete_resourcebase: verify that anonymous user cannot
        # access the layer delete page but redirected to login
        response = self.client.get(reverse('layer_remove', args=(layer.typename,)))
        self.assertEquals(response.status_code, 302)

        # 4. change_resourcebase_metadata
        # 4.1 has not change_resourcebase_metadata: verify that anonymous user
        # cannot access the layer metadata page but redirected to login
        response = self.client.get(reverse('layer_metadata', args=(layer.typename,)))
        self.assertEquals(response.status_code, 302)

        # 5 N\A? 6 is an integration test...

        # 7. change_layer_style
        # 7.1 has not change_layer_style: verify that anonymous user cannot access
        # the layer style page but redirected to login
        response = self.client.get(reverse('layer_style_manage', args=(layer.typename,)))
        self.assertEquals(response.status_code, 302)

    """
    AF: This test must be refactored. Opening an issue for that.
    def test_permissions(self):
        # Test permissions on a layer

        # grab norman
        norman = get_user_model().objects.get(username="norman")

        thefile = os.path.join(
            gisdata.VECTOR_DATA,
            'san_andres_y_providencia_poi.shp')
        layer = file_upload(thefile, overwrite=True)
        check_layer(layer)

        # we need some time to have the service up and running
        time.sleep(20)

        # Set the layer private for not authenticated users
        layer.set_permissions({'users': {'AnonymousUser': []}})

        url = 'http://localhost:8080/geoserver/geonode/wms?' \
            'LAYERS=geonode%3Asan_andres_y_providencia_poi&STYLES=' \
            '&FORMAT=image%2Fpng&SERVICE=WMS&VERSION=1.1.1&REQUEST=GetMap' \
            '&SRS=EPSG%3A4326' \
            '&BBOX=-81.394599749999,13.316009005566,' \
            '-81.370560451855,13.372728455566' \
            '&WIDTH=217&HEIGHT=512'

        # test view_resourcebase permission on anonymous user
        request = urllib2.Request(url)
        response = urllib2.urlopen(request)
        self.assertTrue(
            response.info().getheader('Content-Type'),
            'application/vnd.ogc.se_xml;charset=UTF-8'
        )

        # test WMS with authenticated user that has not view_resourcebase:
        # the layer must be not accessible (response is xml)
        request = urllib2.Request(url)
        base64string = base64.encodestring(
            '%s:%s' % ('norman', 'norman')).replace('\n', '')
        request.add_header("Authorization", "Basic %s" % base64string)
        response = urllib2.urlopen(request)
        self.assertTrue(
            response.info().getheader('Content-Type'),
            'application/vnd.ogc.se_xml;charset=UTF-8'
        )

        # test WMS with authenticated user that has view_resourcebase: the layer
        # must be accessible (response is image)
        assign_perm('view_resourcebase', norman, layer.get_self_resource())
        request = urllib2.Request(url)
        base64string = base64.encodestring(
            '%s:%s' % ('norman', 'norman')).replace('\n', '')
        request.add_header("Authorization", "Basic %s" % base64string)
        response = urllib2.urlopen(request)
        self.assertTrue(response.info().getheader('Content-Type'), 'image/png')

        # test change_layer_data
        # would be nice to make a WFS/T request and test results, but this
        # would work only on PostGIS layers

        # test change_layer_style
        url = 'http://localhost:8000/gs/rest/styles/san_andres_y_providencia_poi.xml'
        sld = ""<?xml version="1.0" encoding="UTF-8"?>
<sld:StyledLayerDescriptor xmlns:sld="http://www.opengis.net/sld"
xmlns:gml="http://www.opengis.net/gml" xmlns:ogc="http://www.opengis.net/ogc"
xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" version="1.0.0"
xsi:schemaLocation="http://www.opengis.net/sld http://schemas.opengis.net/sld/1.0.0/StyledLayerDescriptor.xsd">
   <sld:NamedLayer>
      <sld:Name>geonode:san_andres_y_providencia_poi</sld:Name>
      <sld:UserStyle>
         <sld:Name>san_andres_y_providencia_poi</sld:Name>
         <sld:Title>san_andres_y_providencia_poi</sld:Title>
         <sld:IsDefault>1</sld:IsDefault>
         <sld:FeatureTypeStyle>
            <sld:Rule>
               <sld:PointSymbolizer>
                  <sld:Graphic>
                     <sld:Mark>
                        <sld:Fill>
                           <sld:CssParameter name="fill">#8A7700
                           </sld:CssParameter>
                        </sld:Fill>
                        <sld:Stroke>
                           <sld:CssParameter name="stroke">#bbffff
                           </sld:CssParameter>
                        </sld:Stroke>
                     </sld:Mark>
                     <sld:Size>10</sld:Size>
                  </sld:Graphic>
               </sld:PointSymbolizer>
            </sld:Rule>
         </sld:FeatureTypeStyle>
      </sld:UserStyle>
   </sld:NamedLayer>
</sld:StyledLayerDescriptor>""

        # user without change_layer_style cannot edit it
        self.client.login(username='norman', password='norman')
        response = self.client.put(url, sld, content_type='application/vnd.ogc.sld+xml')
        self.assertEquals(response.status_code, 401)

        # user with change_layer_style can edit it
        assign_perm('change_layer_style', norman, layer)
        response = self.client.put(url, sld, content_type='application/vnd.ogc.sld+xml')
        self.assertEquals(response.status_code, 200)

        # Clean up and completely delete the layer
        layer.delete()
    """

    @unittest.skipIf(
        hasattr(settings, 'SKIP_GEOSERVER_TEST') and
        settings.SKIP_GEOSERVER_TEST,
        'Temporarily skip this test until fixed')
    def test_map_download(self):
        """Test the correct permissions on layers on map download"""
        create_models(type='map')
        create_maplayers()
        # Get a Map
        the_map = Map.objects.get(title='GeoNode Default Map')

        # Get a MapLayer and set the parameters as it is local and not a background
        # and leave it alone in the map
        map_layer = the_map.layer_set.get(name='geonode:CA')
        map_layer.local = True
        map_layer.group = 'overlay'
        map_layer.save()
        the_map.layer_set.all().delete()
        the_map.layer_set.add(map_layer)

        # Get the Layer and set the permissions for bobby to it and the map
        bobby = Profile.objects.get(username='bobby')
        the_layer = Layer.objects.get(typename='geonode:CA')
        remove_perm('download_resourcebase', bobby, the_layer.get_self_resource())
        remove_perm('download_resourcebase', Group.objects.get(name='anonymous'),
                    the_layer.get_self_resource())
        assign_perm('view_resourcebase', bobby, the_layer.get_self_resource())
        assign_perm('download_resourcebase', bobby, the_map.get_self_resource())

        self.client.login(username='bobby', password='bob')

        response = self.client.get(reverse('map_download', args=(the_map.id,)))
        self.assertTrue('Could not find downloadable layers for this map' in response.content)

    @unittest.skipIf(
        hasattr(settings, 'SKIP_GEOSERVER_TEST') and
        settings.SKIP_GEOSERVER_TEST,
        'Temporarily skip this test until fixed')
    def test_not_superuser_permissions(self):

        # grab bobby
        bob = get_user_model().objects.get(username='bobby')

        # grab a layer
        layer = Layer.objects.all()[0]
        layer.set_default_permissions()
        # verify bobby has view/change permissions on it but not manage
        self.assertFalse(
            bob.has_perm(
                'change_resourcebase_permissions',
                layer.get_self_resource()))

        self.assertTrue(self.client.login(username='bobby', password='bob'))

        # 1. view_resourcebase
        # 1.1 has view_resourcebase: verify that bobby can access the layer
        # detail page
        self.assertTrue(
            bob.has_perm(
                'view_resourcebase',
                layer.get_self_resource()))

        response = self.client.get(reverse('layer_detail', args=(layer.typename,)))
        self.assertEquals(response.status_code, 200)
        # 1.2 has not view_resourcebase: verify that bobby can not access the
        # layer detail page
        remove_perm('view_resourcebase', bob, layer.get_self_resource())
        anonymous_group = Group.objects.get(name='anonymous')
        remove_perm('view_resourcebase', anonymous_group, layer.get_self_resource())
        response = self.client.get(reverse('layer_detail', args=(layer.typename,)))
        self.assertEquals(response.status_code, 401)

        # 2. change_resourcebase
        # 2.1 has not change_resourcebase: verify that bobby cannot access the
        # layer replace page
        response = self.client.get(reverse('layer_replace', args=(layer.typename,)))
        self.assertEquals(response.status_code, 401)
        # 2.2 has change_resourcebase: verify that bobby can access the layer
        # replace page
        assign_perm('change_resourcebase', bob, layer.get_self_resource())
        self.assertTrue(
            bob.has_perm(
                'change_resourcebase',
                layer.get_self_resource()))
        response = self.client.get(reverse('layer_replace', args=(layer.typename,)))
        self.assertEquals(response.status_code, 200)

        # 3. delete_resourcebase
        # 3.1 has not delete_resourcebase: verify that bobby cannot access the
        # layer delete page
        response = self.client.get(reverse('layer_remove', args=(layer.typename,)))
        self.assertEquals(response.status_code, 401)
        # 3.2 has delete_resourcebase: verify that bobby can access the layer
        # delete page
        assign_perm('delete_resourcebase', bob, layer.get_self_resource())
        self.assertTrue(
            bob.has_perm(
                'delete_resourcebase',
                layer.get_self_resource()))
        response = self.client.get(reverse('layer_remove', args=(layer.typename,)))
        self.assertEquals(response.status_code, 200)

        # 4. change_resourcebase_metadata
        # 4.1 has not change_resourcebase_metadata: verify that bobby cannot
        # access the layer metadata page
        response = self.client.get(reverse('layer_metadata', args=(layer.typename,)))
        self.assertEquals(response.status_code, 401)
        # 4.2 has delete_resourcebase: verify that bobby can access the layer
        # delete page
        assign_perm('change_resourcebase_metadata', bob, layer.get_self_resource())
        self.assertTrue(
            bob.has_perm(
                'change_resourcebase_metadata',
                layer.get_self_resource()))
        response = self.client.get(reverse('layer_metadata', args=(layer.typename,)))
        self.assertEquals(response.status_code, 200)

        # 5. change_resourcebase_permissions
        # should be impossible for the user without change_resourcebase_permissions
        # to change permissions as the permission form is not available in the
        # layer detail page?

        # 6. change_layer_data
        # must be done in integration test sending a WFS-T request with CURL

        # 7. change_layer_style
        # 7.1 has not change_layer_style: verify that bobby cannot access
        # the layer style page
        response = self.client.get(reverse('layer_style_manage', args=(layer.typename,)))
        self.assertEquals(response.status_code, 401)
        # 7.2 has change_layer_style: verify that bobby can access the
        # change layer style page
        assign_perm('change_layer_style', bob, layer)
        self.assertTrue(
            bob.has_perm(
                'change_layer_style',
                layer))
        response = self.client.get(reverse('layer_style_manage', args=(layer.typename,)))
        self.assertEquals(response.status_code, 200)

    @unittest.skipIf(
        hasattr(settings, 'SKIP_GEOSERVER_TEST') and
        settings.SKIP_GEOSERVER_TEST,
        'Temporarily skip this test until fixed')
    def test_unpublished(self):
        """Test permissions on an unpublished layer
        """

        thefile = os.path.join(
            gisdata.VECTOR_DATA,
            'san_andres_y_providencia_poi.shp')
        layer = file_upload(thefile, overwrite=True)
        layer.set_default_permissions()
        check_layer(layer)

        # we need some time to have the service up and running
        time.sleep(20)

        # request getCapabilities: layer must be there as it is published and
        # advertised: we need to check if in response there is
        # <Name>geonode:san_andres_y_providencia_water</Name>
        url = 'http://localhost:8080/geoserver/ows?' \
            'service=wms&version=1.3.0&request=GetCapabilities'
        str_to_check = '<Name>geonode:san_andres_y_providencia_poi</Name>'
        request = urllib2.Request(url)
        response = urllib2.urlopen(request)
        self.assertTrue(any(str_to_check in s for s in response.readlines()))

        # by default the uploaded layer is
        self.assertTrue(layer.is_published, True)

        # Clean up and completely delete the layer
        layer.delete()

        # with settings disabled
        with self.settings(RESOURCE_PUBLISHING=True):

            thefile = os.path.join(
                gisdata.VECTOR_DATA,
                'san_andres_y_providencia_administrative.shp')
            layer = file_upload(thefile, overwrite=True)
            layer.set_default_permissions()
            check_layer(layer)

            # we need some time to have the service up and running
            time.sleep(20)

            str_to_check = '<Name>san_andres_y_providencia_administrative</Name>'

            # by default the uploaded layer must be unpublished
            self.assertEqual(layer.is_published, False)

            # check the layer is not in GetCapabilities
            request = urllib2.Request(url)
            response = urllib2.urlopen(request)
            self.assertFalse(any(str_to_check in s for s in response.readlines()))

            # now test with published layer
            resource = layer.get_self_resource()
            resource.is_published = True
            resource.save()

            request = urllib2.Request(url)
            response = urllib2.urlopen(request)
            self.assertTrue(any(str_to_check in s for s in response.readlines()))

            # Clean up and completely delete the layer
            layer.delete()


class GeoNodeThumbnailTest(TestCase):

    """Tests thumbnails behavior for layers and maps.
    """

    def setUp(self):
        call_command('loaddata', 'people_data', verbosity=0)

    def tearDown(self):
        pass

    def test_layer_thumbnail(self):
        """Test the layer save method generates a thumbnail link
        """

        self.client.login(username='norman', password='norman')

        # TODO: Would be nice to ensure the name is available before
        # running the test...
        norman = get_user_model().objects.get(username="norman")
        saved_layer = file_upload(
            os.path.join(
                gisdata.VECTOR_DATA,
                "san_andres_y_providencia_poi.shp"),
            name="san_andres_y_providencia_poi_by_norman",
            user=norman,
            overwrite=True,
        )

        thumbnail_url = saved_layer.get_thumbnail_url()

        assert thumbnail_url != staticfiles.static(settings.MISSING_THUMBNAIL)

    @unittest.skipIf(
        hasattr(settings, 'SKIP_GEOSERVER_TEST') and
        settings.SKIP_GEOSERVER_TEST,
        'Temporarily skip this test until fixed')
    def test_map_thumbnail(self):
        """Test the map save method generates a thumbnail link
        """
        self.client.login(username='norman', password='norman')

        # TODO: Would be nice to ensure the name is available before
        # running the test...
        norman = get_user_model().objects.get(username="norman")
        saved_layer = file_upload(
            os.path.join(
                gisdata.VECTOR_DATA,
                "san_andres_y_providencia_poi.shp"),
            name="san_andres_y_providencia_poi_by_norman",
            user=norman,
            overwrite=True,
        )
        saved_layer.set_default_permissions()
        map_obj = Map(owner=norman, zoom=0,
                      center_x=0, center_y=0)
        map_obj.create_from_layer_list(norman, [saved_layer], 'title', '')

        thumbnail_url = map_obj.get_thumbnail_url()

        assert thumbnail_url != staticfiles.static(settings.MISSING_THUMBNAIL)


class GeoNodeMapPrintTest(TestCase):

    """Tests geonode.maps print
    """

    def setUp(self):
        call_command('loaddata', 'people_data', verbosity=0)

    def tearDown(self):
        pass

    def testPrintProxy(self):
        """ Test the PrintProxyMiddleware if activated.
            It should respect the permissions on private layers.
        """

        if 'geonode.middleware.PrintProxyMiddleware' in settings.MIDDLEWARE_CLASSES:
            # STEP 1: Import a layer
            from geonode.maps.models import Map

            self.client.login(username='norman', password='norman')

            # TODO: Would be nice to ensure the name is available before
            # running the test...
            norman = get_user_model().objects.get(username="norman")
            saved_layer = file_upload(
                os.path.join(
                    gisdata.VECTOR_DATA,
                    "san_andres_y_providencia_poi.shp"),
                name="san_andres_y_providencia_poi_by_norman",
                user=norman,
                overwrite=True,
            )
            # Set the layer private
            saved_layer.set_permissions(
                {'users': {'AnonymousUser': ['view_resourcebase']}})

            url = reverse(
                'layer_metadata',
                args=[
                    saved_layer.service_typename])

            # check is accessible while logged in
            resp = self.client.get(url)
            self.assertEquals(resp.status_code, 200)

            # check is inaccessible when not logged in
            self.client.logout()
            resp = self.client.get(url)
            self.assertEquals(resp.status_code, 302)

            # STEP 2: Create a Map with that layer

            map_obj = Map(owner=norman, zoom=0,
                          center_x=0, center_y=0)
            map_obj.create_from_layer_list(norman, [saved_layer], 'title', '')

            # STEP 3: Print the map

            print_url = settings.OGC_SERVER['default'][
                'LOCATION'] + 'pdf/create.json'

            post_payload = {
                'dpi': 75,
                'layers': [
                    {
                        'baseURL': settings.OGC_SERVER['default']['LOCATION'] +
                        'wms?SERVICE=WMS&',
                        'format': "image/png",
                        'customParams': {
                            'TILED': True,
                            'TRANSPARENT': True},
                        'layers': [
                            saved_layer.service_typename],
                        'opacity': 1,
                        'singleTile': False,
                        'type': 'WMS'}],
                'layout': 'A4 portrait',
                'mapTitle': 'test',
                'outputFilename': 'print',
                'srs': getattr(settings, 'DEFAULT_MAP_CRS', 'EPSG:900913'),
                'units': 'm'}

            self.client.post(print_url, post_payload)

            # Test the layer is still inaccessible as non authenticated
            resp = self.client.get(url)
            self.assertEquals(resp.status_code, 302)

        else:
            pass


class GeoNodeGeoServerSync(TestCase):

    """Tests GeoNode/GeoServer syncronization
    """

    def setUp(self):
        call_command('loaddata', 'people_data', verbosity=0)

    def tearDown(self):
        pass

    def test_set_attributes_from_geoserver(self):
        """Test attributes syncronization
        """

        # upload a shapefile
        shp_file = os.path.join(
            gisdata.VECTOR_DATA,
            'san_andres_y_providencia_poi.shp')
        layer = file_upload(shp_file)

        # set attributes for resource
        for attribute in layer.attribute_set.all():
            attribute.attribute_label = '%s_label' % attribute.attribute
            attribute.description = '%s_description' % attribute.attribute
            attribute.save()

        # sync the attributes with GeoServer
        set_attributes_from_geoserver(layer)

        # tests if everything is synced properly
        for attribute in layer.attribute_set.all():
            self.assertEquals(
                attribute.attribute_label,
                '%s_label' % attribute.attribute
            )
            self.assertEquals(
                attribute.description,
                '%s_description' % attribute.attribute
            )


class GeoNodeLayerTest(TestCase):
    def setUp(self):
        pass

    def tearDown(self):
        pass

    @unittest.skipIf(
        hasattr(settings, 'SKIP_GEOSERVER_TEST') and
        settings.SKIP_GEOSERVER_TEST,
        'Temporarily skip this test until fixed')
    def test_get_files(self):

        # Check that a well-formed Shapefile has its components all picked up
        d = None
        try:
            d = tempfile.mkdtemp()
            for f in ("foo.shp", "foo.shx", "foo.prj", "foo.dbf"):
                path = os.path.join(d, f)
                # open and immediately close to create empty file
                open(path, 'w').close()

            gotten_files = get_files(os.path.join(d, "foo.shp"))
            gotten_files = dict((k, v[len(d) + 1:])
                                for k, v in gotten_files.iteritems())
            self.assertEquals(gotten_files, dict(shp="foo.shp", shx="foo.shx",
                                                 prj="foo.prj", dbf="foo.dbf"))
        finally:
            if d is not None:
                shutil.rmtree(d)

        # Check that a Shapefile missing required components raises an
        # exception
        d = None
        try:
            d = tempfile.mkdtemp()
            for f in ("foo.shp", "foo.shx", "foo.prj"):
                path = os.path.join(d, f)
                # open and immediately close to create empty file
                open(path, 'w').close()

            self.assertRaises(
                GeoNodeException,
                lambda: get_files(
                    os.path.join(
                        d,
                        "foo.shp")))
        finally:
            if d is not None:
                shutil.rmtree(d)

        # Check that including an SLD with a valid shapefile results in the SLD
        # getting picked up
        d = None
        try:
            d = tempfile.mkdtemp()
            for f in ("foo.shp", "foo.shx", "foo.prj", "foo.dbf", "foo.sld"):
                path = os.path.join(d, f)
                # open and immediately close to create empty file
                open(path, 'w').close()

            gotten_files = get_files(os.path.join(d, "foo.shp"))
            gotten_files = dict((k, v[len(d) + 1:])
                                for k, v in gotten_files.iteritems())
            self.assertEquals(
                gotten_files,
                dict(
                    shp="foo.shp",
                    shx="foo.shx",
                    prj="foo.prj",
                    dbf="foo.dbf",
                    sld="foo.sld"))
        finally:
            if d is not None:
                shutil.rmtree(d)

        # Check that capitalized extensions are ok
        d = None
        try:
            d = tempfile.mkdtemp()
            for f in ("foo.SHP", "foo.SHX", "foo.PRJ", "foo.DBF"):
                path = os.path.join(d, f)
                # open and immediately close to create empty file
                open(path, 'w').close()

            gotten_files = get_files(os.path.join(d, "foo.SHP"))
            gotten_files = dict((k, v[len(d) + 1:])
                                for k, v in gotten_files.iteritems())
            self.assertEquals(gotten_files, dict(shp="foo.SHP", shx="foo.SHX",
                                                 prj="foo.PRJ", dbf="foo.DBF"))
        finally:
            if d is not None:
                shutil.rmtree(d)

        # Check that mixed capital and lowercase extensions are ok
        d = None
        try:
            d = tempfile.mkdtemp()
            for f in ("foo.SHP", "foo.shx", "foo.pRJ", "foo.DBF"):
                path = os.path.join(d, f)
                # open and immediately close to create empty file
                open(path, 'w').close()

            gotten_files = get_files(os.path.join(d, "foo.SHP"))
            gotten_files = dict((k, v[len(d) + 1:])
                                for k, v in gotten_files.iteritems())
            self.assertEquals(gotten_files, dict(shp="foo.SHP", shx="foo.shx",
                                                 prj="foo.pRJ", dbf="foo.DBF"))
        finally:
            if d is not None:
                shutil.rmtree(d)

        # Check that including both capital and lowercase extensions raises an
        # exception
        d = None
        try:
            d = tempfile.mkdtemp()
            files = (
                "foo.SHP",
                "foo.SHX",
                "foo.PRJ",
                "foo.DBF",
                "foo.shp",
                "foo.shx",
                "foo.prj",
                "foo.dbf")
            for f in files:
                path = os.path.join(d, f)
                # open and immediately close to create empty file
                open(path, 'w').close()

            # Only run the tests if this is a case sensitive OS
            if len(os.listdir(d)) == len(files):
                self.assertRaises(
                    GeoNodeException,
                    lambda: get_files(
                        os.path.join(
                            d,
                            "foo.SHP")))
                self.assertRaises(
                    GeoNodeException,
                    lambda: get_files(
                        os.path.join(
                            d,
                            "foo.shp")))

        finally:
            if d is not None:
                shutil.rmtree(d)

        # Check that including both capital and lowercase PRJ (this is
        # special-cased in the implementation)
        d = None
        try:
            d = tempfile.mkdtemp()
            files = ("foo.SHP", "foo.SHX", "foo.PRJ", "foo.DBF", "foo.prj")
            for f in files:
                path = os.path.join(d, f)
                # open and immediately close to create empty file
                open(path, 'w').close()

            # Only run the tests if this is a case sensitive OS
            if len(os.listdir(d)) == len(files):
                self.assertRaises(
                    GeoNodeException,
                    lambda: get_files(
                        os.path.join(
                            d,
                            "foo.SHP")))
                self.assertRaises(
                    GeoNodeException,
                    lambda: get_files(
                        os.path.join(
                            d,
                            "foo.shp")))
        finally:
            if d is not None:
                shutil.rmtree(d)

        # Check that including both capital and lowercase SLD (this is
        # special-cased in the implementation)
        d = None
        try:
            d = tempfile.mkdtemp()
            files = (
                "foo.SHP",
                "foo.SHX",
                "foo.PRJ",
                "foo.DBF",
                "foo.SLD",
                "foo.sld")
            for f in files:
                path = os.path.join(d, f)
                # open and immediately close to create empty file
                open(path, 'w').close()

            # Only run the tests if this is a case sensitive OS
            if len(os.listdir(d)) == len(files):
                self.assertRaises(
                    GeoNodeException,
                    lambda: get_files(
                        os.path.join(
                            d,
                            "foo.SHP")))
                self.assertRaises(
                    GeoNodeException,
                    lambda: get_files(
                        os.path.join(
                            d,
                            "foo.shp")))
        finally:
            if d is not None:
                shutil.rmtree(d)