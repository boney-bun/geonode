# -*- coding: utf-8 -*-
#########################################################################
#
# Copyright (C) 2018 OSGeo
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
##################################O#######################################
import os
import shutil
from optparse import make_option

from django.conf import settings
from django.core.management import call_command
from django.core.management.base import BaseCommand, CommandError
from geonode.base.models import Backup

from geonode.base.management.commands import helpers
from geonode.qgis_server.management.commands.helpers import Config
from geonode.utils import designals, resignals


class Command(BaseCommand):

    help = 'Backup the GeoNode application data'

    option_list = BaseCommand.option_list + Config.qgis_server_option_list + (
        Config.option,
        make_option(
            '--backup-id',
            default=0,
            dest='backup_id',
            type='int',
            help='Backup model id to be updated for this backup archive.'
        ),
        make_option(
            '-i',
            '--ignore-errors',
            action='store_true',
            dest='ignore_errors',
            default=False,
            help='Stop after any errors are encountered.'),
        make_option(
            '-f',
            '--force',
            action='store_true',
            dest='force_exec',
            default=False,
            help='Forces the execution without asking for confirmation.'),
        make_option(
            '--skip-qgis-server',
            action='store_true',
            dest='skip_qgis_server',
            default=False,
            help='Skips QGIS Server backup'),
        make_option(
            '--backup-dir',
            dest='backup_dir',
            type="string",
            help='Destination folder where to store the backup archive. '
                 'It must be writable.'))

    def create_qgis_server_backup(self, config, settings, target_folder):
        """Backup QGIS Server project data

        :param config:
        :type config: Config

        :param settings:
        :type settings: dict

        :param target_folder:
        :type target_folder: basestring
        """
        # Create QGIS Server Backup
        qgisserver_bk_file = os.path.join(
            target_folder, 'qgis_server_data.zip')

        try:

            helpers.zip_dir(config.qs_data_dir, qgisserver_bk_file)

            print 'Successfully backup QGIS Server data: {}'.format(
                qgisserver_bk_file)
        except BaseException as e:
            print "Could not successfully backup QGIS Server data"
            raise e

    def handle(self, **options):
        # ignore_errors = options.get('ignore_errors')
        config = Config(options)
        force_exec = options.get('force_exec')
        backup_dir = options.get('backup_dir')
        skip_qgis_server = options.get('skip_qgis_server')
        backup_id = options.get('backup_id')

        if not backup_dir or len(backup_dir) == 0:
            raise CommandError("Destination folder '--backup-dir' is mandatory")

        print "Before proceeding with the Backup, please ensure that:"
        print " 1. The backend (DB or whatever) is accessible and you have rights"
        message = 'You want to proceed?'

        if force_exec or helpers.confirm(prompt=message, resp=False):

            # Create Target Folder
            dir_time_suffix = helpers.get_dir_time_suffix()
            target_folder = os.path.join(backup_dir, dir_time_suffix)
            if not os.path.exists(target_folder):
                os.makedirs(target_folder)
            # Temporary folder to store backup files. It will be deleted at the end.
            os.chmod(target_folder, 0777)

            # Update backup object info if available
            try:
                backup_filename = os.path.join(
                    backup_dir, '{}.zip'.format(dir_time_suffix))
                Backup.objects.filter(pk=backup_id).update(
                    location=backup_filename)
            except Backup.DoesNotExist:
                # It means this is executed directly from command line
                pass

            if not skip_qgis_server:
                self.create_qgis_server_backup(
                    config, settings, target_folder)
            else:
                print("Skipping QGIS Server backup")

            try:
                # Deactivate GeoNode Signals
                print "Deactivating GeoNode Signals..."
                designals()
                print "...done!"

                # Dump Fixtures
                for app_name, dump_name in zip(config.app_names, config.dump_names):
                    print "Dumping '"+app_name+"' into '"+dump_name+".json'."
                    # Point stdout at a file for dumping data to.
                    output = open(os.path.join(target_folder, dump_name+'.json'), 'w')
                    call_command('dumpdata', app_name, format='json', indent=2, natural=True, stdout=output)
                    output.close()

                # Store Media Root
                media_root = settings.MEDIA_ROOT
                media_folder = os.path.join(target_folder, helpers.MEDIA_ROOT)
                if not os.path.exists(media_folder):
                    os.makedirs(media_folder)

                helpers.copy_tree(media_root, media_folder)
                print "Saved Media Files from '"+media_root+"'."

                # Store Static Root
                static_root = settings.STATIC_ROOT
                static_folder = os.path.join(target_folder, helpers.STATIC_ROOT)
                if not os.path.exists(static_folder):
                    os.makedirs(static_folder)

                helpers.copy_tree(static_root, static_folder)
                print "Saved Static Root from '"+static_root+"'."

                # Store Static Folders
                static_folders = settings.STATICFILES_DIRS
                static_files_folders = os.path.join(target_folder, helpers.STATICFILES_DIRS)
                if not os.path.exists(static_files_folders):
                    os.makedirs(static_files_folders)

                for static_files_folder in static_folders:
                    static_folder = os.path.join(static_files_folders,
                                                 os.path.basename(os.path.normpath(static_files_folder)))
                    if not os.path.exists(static_folder):
                        os.makedirs(static_folder)

                    helpers.copy_tree(static_files_folder, static_folder)
                    print "Saved Static Files from '"+static_files_folder+"'."

                # Store Template Folders
                template_folders = settings.TEMPLATE_DIRS
                template_files_folders = os.path.join(target_folder, helpers.TEMPLATE_DIRS)
                if not os.path.exists(template_files_folders):
                    os.makedirs(template_files_folders)

                for template_files_folder in template_folders:
                    template_folder = os.path.join(template_files_folders,
                                                   os.path.basename(os.path.normpath(template_files_folder)))
                    if not os.path.exists(template_folder):
                        os.makedirs(template_folder)

                    helpers.copy_tree(template_files_folder, template_folder)
                    print "Saved Template Files from '"+template_files_folder+"'."

                # Store Locale Folders
                locale_folders = settings.LOCALE_PATHS
                locale_files_folders = os.path.join(target_folder, helpers.LOCALE_PATHS)
                if not os.path.exists(locale_files_folders):
                    os.makedirs(locale_files_folders)

                for locale_files_folder in locale_folders:
                    locale_folder = os.path.join(locale_files_folders,
                                                 os.path.basename(os.path.normpath(locale_files_folder)))
                    if not os.path.exists(locale_folder):
                        os.makedirs(locale_folder)

                    helpers.copy_tree(locale_files_folder, locale_folder)
                    print "Saved Locale Files from '"+locale_files_folder+"'."

                # Create Final ZIP Archive
                helpers.zip_dir(target_folder, os.path.join(backup_dir, dir_time_suffix+'.zip'))

                # Clean-up Temp Folder
                try:
                    shutil.rmtree(target_folder)
                except:
                    print "WARNING: Could not be possible to delete the temp folder: '" + str(target_folder) + "'"

                print "Backup Finished. Archive generated."

                return str(os.path.join(backup_dir, dir_time_suffix+'.zip'))
            finally:
                # Reactivate GeoNode Signals
                print "Reactivating GeoNode Signals..."
                resignals()
                print "...done!"