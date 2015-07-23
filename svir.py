# -*- coding: utf-8 -*-
"""
/***************************************************************************
 Svir
                                 A QGIS plugin
 OpenQuake Social Vulnerability and Integrated Risk
                              -------------------
        begin                : 2013-10-24
        copyright            : (C) 2013-2015 by GEM Foundation
        email                : devops@openquake.org
 ***************************************************************************/

# OpenQuake is free software: you can redistribute it and/or modify it
# under the terms of the GNU Affero General Public License as published
# by the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# OpenQuake is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU Affero General Public License
# along with OpenQuake.  If not, see <http://www.gnu.org/licenses/>.
"""
import json
import os.path
import tempfile
import uuid
import fileinput
import re
from copy import deepcopy

from math import floor, ceil
from download_layer_dialog import DownloadLayerDialog
from download_platform_data_worker import DownloadPlatformDataWorker
from download_platform_project_worker import DownloadPlatformProjectWorker
from metadata_utilities import write_iso_metadata_file

from PyQt4.QtCore import (QSettings,
                          QTranslator,
                          QCoreApplication,
                          qVersion,
                          QUrl,
                          )

from PyQt4.QtGui import (QAction,
                         QIcon,
                         QColor,
                         QFileDialog,
                         QDesktopServices,
                         QMessageBox,
                         )

from qgis.core import (QgsVectorLayer,
                       QgsMapLayerRegistry,
                       QgsMessageLog,
                       QgsMapLayer,
                       QgsVectorFileWriter,
                       QgsGraduatedSymbolRendererV2,
                       QgsSymbolV2, QgsVectorGradientColorRampV2,
                       QgsRuleBasedRendererV2,
                       QgsFillSymbolV2,
                       QgsProject,
                       )

from qgis.gui import QgsMessageBar

from upload_dialog import UploadDialog

from calculate_utils import calculate_composite_variable

from process_layer import ProcessLayer

import resources_rc  # pylint: disable=W0611  # NOQA

from third_party.requests.sessions import Session

from select_input_layers_dialog import SelectInputLayersDialog
from attribute_selection_dialog import AttributeSelectionDialog
from transformation_dialog import TransformationDialog
from select_sv_variables_dialog import SelectSvVariablesDialog
from settings_dialog import SettingsDialog
from weight_data_dialog import WeightDataDialog
from upload_settings_dialog import UploadSettingsDialog
from projects_manager_dialog import ProjectsManagerDialog

from import_sv_data import get_loggedin_downloader

from utils import (tr,
                   WaitCursorManager,
                   assign_default_weights,
                   clear_progress_message_bar,
                   SvNetworkError, ask_for_download_destination,
                   files_exist_in_destination, confirm_overwrite,
                   platform_login,
                   get_credentials,
                   update_platform_project,
                   count_heading_commented_lines,
                   replace_fields,
                   toggle_select_features_widget,
                   )
from abstract_worker import start_worker
from shared import (SVIR_PLUGIN_VERSION,
                    DEBUG,
                    PROJECT_TEMPLATE,
                    THEME_TEMPLATE,
                    INDICATOR_TEMPLATE,
                    )
from aggregate_loss_by_zone import (calculate_zonal_stats,
                                    purge_zones_without_loss_points,
                                    )


class Svir:

    def __init__(self, iface):
        # Save reference to the QGIS interface
        self.iface = iface
        self.canvas = self.iface.mapCanvas()
        # initialize plugin directory
        self.plugin_dir = os.path.dirname(__file__)
        # initialize locale
        locale = QSettings().value("locale/userLocale")[0:2]
        locale_path = os.path.join(self.plugin_dir, 'i18n',
                                   'svir_{}.qm'.format(locale))

        if os.path.exists(locale_path):
            self.translator = QTranslator()
            self.translator.load(locale_path)

            if qVersion() > '4.3.3':
                QCoreApplication.installTranslator(self.translator)

        # our own toolbar
        self.toolbar = None
        # keep a list of the menu items, in order to easily unload them later
        self.registered_actions = dict()

        # keep track of the supplemental information for each layer
        # layer_id -> {}
        # where each dict contains 'platform_layer_id',
        # 'selected_project_definition_idx', 'project_definitions'
        self.supplemental_information = {}

        self.iface.currentLayerChanged.connect(self.current_layer_changed)
        QgsMapLayerRegistry.instance().layersAdded.connect(self.layers_added)
        QgsMapLayerRegistry.instance().layersRemoved.connect(
            self.layers_removed)

    def initGui(self):
        # create our own toolbar
        self.toolbar = self.iface.addToolBar('SVIR')
        self.toolbar.setObjectName('SVIRToolBar')

        # Action to activate the modal dialog to import socioeconomic
        # data from the platform
        self.add_menu_item("import_sv_variables",
                           ":/plugins/svir/load.svg",
                           u"&Load socioeconomic indicators"
                           " from the OpenQuake Platform",
                           self.import_sv_variables,
                           enable=True,
                           add_to_layer_actions=False)
        # Action to activate the modal dialog to import socioeconomic
        # data from the platform
        self.add_menu_item("import_layer",
                           ":/plugins/svir/load_layer.svg",
                           u"&Import project from the OpenQuake Platform",
                           self.download_layer,
                           enable=True,
                           add_to_layer_actions=False)
        # Action to activate the modal dialog to select a layer and one of its
        # attributes, in order to transform that attribute
        self.add_menu_item("transform_attributes",
                           ":/plugins/svir/transform.svg",
                           u"&Transform attributes",
                           self.transform_attributes,
                           enable=False,
                           add_to_layer_actions=True)
        # Action to manage the projects
        self.add_menu_item("project_definitions_manager",
                           ":/plugins/svir/copy.svg",
                           u"&Manage project definitions",
                           self.project_definitions_manager,
                           enable=False,
                           add_to_layer_actions=True)

        # Action to activate the modal dialog to choose weighting of the
        # data from the platform
        self.add_menu_item("weight_data",
                           ":/plugins/svir/weights.svg",
                           u"&Weight data and calculate indices",
                           self.weight_data,
                           enable=False,
                           add_to_layer_actions=True)
        # Action to activate the modal dialog to guide the user through loss
        # aggregation by zone
        self.add_menu_item("aggregate_losses",
                           ":/plugins/svir/aggregate.svg",
                           u"&Aggregate loss by zone",
                           self.aggregate_losses,
                           enable=True,
                           add_to_layer_actions=False)

        # Action to upload
        self.add_menu_item("upload",
                           ":/plugins/svir/upload.svg",
                           u"&Upload project to the OpenQuake Platform",
                           self.upload,
                           enable=False,
                           add_to_layer_actions=True)
        # Action to activate the modal dialog to set up show_settings for the
        # connection with the platform
        self.add_menu_item("show_settings",
                           ":/plugins/svir/settings.svg",
                           u"&OpenQuake Platform connection settings",
                           self.show_settings,
                           enable=True)
        # Action to open the plugin's manual
        self.add_menu_item("help",
                           ":/plugins/svir/manual.svg",
                           u"Plugin's &Manual",
                           self.show_manual,
                           enable=True)

        self.update_actions_status()

    def show_manual(self):
        base_url = os.path.abspath(os.path.join(
            __file__, os.path.pardir, 'manual'))
        base_url = os.path.join(base_url, 'index_en.html')
        if not os.path.exists(base_url):
            self.iface.messageBar().pushMessage(
                tr("Error"),
                'Help file not found: %s' % base_url,
                level=QgsMessageBar.CRITICAL)
        url = QUrl.fromLocalFile(base_url)
        QDesktopServices.openUrl(url)

    def layers_added(self):
        self.update_actions_status()

    def layers_removed(self, layer_ids):
        for layer_id in layer_ids:
            self.clear_layer_suppl_info(layer_id)
        self.update_actions_status()

    def sync_layer_suppl_info_from_qgs_project(self, layer_id):
        # synchronize with the qgs project's properties
        # it returns a tuple, with the returned value and a boolean indicating
        # if such property is available
        layer_suppl_info_str, is_available = \
            QgsProject.instance().readEntry('svir', layer_id)
        if is_available and layer_suppl_info_str:
            self.supplemental_information[layer_id] = \
                json.loads(layer_suppl_info_str)
        else:
            self.supplemental_information[layer_id] = {}
        if DEBUG:
            print ("self.supplemental_information[%s] synchronized"
                   " with project, as: %s") % (
                layer_id, self.supplemental_information[layer_id])

    def clear_layer_suppl_info(self, layer_id):
        self.supplemental_information.pop(layer_id, None)
        QgsProject.instance().removeEntry('svir', layer_id)

    def update_layer_suppl_info(self, layer_id, suppl_info):
        self.sync_layer_suppl_info_from_qgs_project(layer_id)
        # TODO: upgrade old project definitions
        # set the QgsProject's property
        QgsProject.instance().writeEntry(
            'svir', layer_id,
            json.dumps(suppl_info,
                       sort_keys=False,
                       indent=2,
                       separators=(',', ': ')))
        if DEBUG:
            print ("Project's property 'supplemental_information[%s]'"
                   " updated: %s") % (
                layer_id, QgsProject.instance().readEntry('svir', layer_id))

    def current_layer_changed(self, layer):
        self.update_actions_status()

    def add_menu_item(self,
                      action_name,
                      icon_path,
                      label,
                      corresponding_method,
                      enable=False,
                      add_to_layer_actions=False,
                      layers_type=QgsMapLayer.VectorLayer
                      ):
        """
        Add an item to the SVIR plugin menu and a corresponding toolbar icon
        @param icon_path: Path of the icon associated to the action
        @param label: Name of the action, visible to the user
        @param corresponding_method: Method called when the action is triggered
        """
        if action_name in self.registered_actions:
            raise NameError("Action %s already registered" % action_name)
        action = QAction(QIcon(icon_path), label, self.iface.mainWindow())
        action.setEnabled(enable)
        action.triggered.connect(corresponding_method)
        self.toolbar.addAction(action)
        self.iface.addPluginToMenu(u"&SVIR", action)
        self.registered_actions[action_name] = action

        if add_to_layer_actions:
            self.iface.legendInterface().addLegendLayerAction(
                action,
                u"SVIR",
                action_name,
                layers_type,
                True)

    def update_actions_status(self):
        # Check if actions can be enabled
        reg = QgsMapLayerRegistry.instance()
        layer_count = len(list(reg.mapLayers()))
        # Enable/disable "transform" action
        self.registered_actions["transform_attributes"].setDisabled(
            layer_count == 0)

        if DEBUG:
            print 'Selected: %s' % self.iface.activeLayer()
        try:
            # Activate actions which require a vector layer to be selected
            if self.iface.activeLayer().type() != QgsMapLayer.VectorLayer:
                raise AttributeError
            self.registered_actions[
                "project_definitions_manager"].setEnabled(True)
            self.registered_actions["weight_data"].setEnabled(True)
            self.registered_actions["transform_attributes"].setEnabled(True)
            self.sync_layer_suppl_info_from_qgs_project(
                self.iface.activeLayer().id())
            suppl_info = self.supplemental_information[
                self.iface.activeLayer().id()]
            selected_idx = suppl_info['selected_project_definition_idx']
            proj_defs = suppl_info['project_definitions']
            proj_def = proj_defs[selected_idx]
            self.registered_actions["upload"].setEnabled(proj_def is not None)
        except KeyError:
            # self.project_definitions[self.iface.activeLayer().id()]
            # is not defined
            pass  # We can still use the weight_data dialog
        except AttributeError:
            # self.iface.activeLayer().id() does not exist
            # or self.iface.activeLayer() is not vector
            self.registered_actions["transform_attributes"].setEnabled(False)
            self.registered_actions["weight_data"].setEnabled(False)
            self.registered_actions["upload"].setEnabled(False)
            self.registered_actions[
                "project_definitions_manager"].setEnabled(False)

    def unload(self):
        # Remove the plugin menu items and toolbar icons
        for action_name in self.registered_actions:
            action = self.registered_actions[action_name]
            # Remove the actions in the layer legend
            self.iface.legendInterface().removeLegendLayerAction(action)
            self.iface.removePluginMenu(u"&SVIR", action)
            self.iface.removeToolBarIcon(action)
        clear_progress_message_bar(self.iface.messageBar())

        #remove connects
        self.iface.currentLayerChanged.disconnect(self.current_layer_changed)
        QgsMapLayerRegistry.instance().layersAdded.disconnect(
            self.layers_added)
        QgsMapLayerRegistry.instance().layersRemoved.disconnect(
            self.layers_removed)

    def aggregate_losses(self):
        """
        Open a modal dialog to select a layer containing zonal data for social
        vulnerability and a layer containing loss data points. After data are
        loaded, calculate_zonal_stats()
        is automatically called, in order to aggregate loss points with
        respect to the same geometries defined for the socioeconomic
        data, and to compute zonal statistics (point count, loss sum,
        and average for each zone)
        """
        # Create the dialog (after translation) and keep reference
        dlg = SelectInputLayersDialog(self.iface)
        # Run the dialog event loop
        # See if OK was pressed
        if dlg.exec_():
            loss_layer_id = dlg.ui.loss_layer_cbx.itemData(
                dlg.ui.loss_layer_cbx.currentIndex())
            loss_layer = QgsMapLayerRegistry.instance().mapLayer(
                loss_layer_id)
            zonal_layer_id = dlg.ui.zonal_layer_cbx.itemData(
                dlg.ui.zonal_layer_cbx.currentIndex())
            zonal_layer = QgsMapLayerRegistry.instance().mapLayer(
                zonal_layer_id)

            # if the two layers have different projections, display an error
            # message and return
            have_same_projection, check_projection_msg = ProcessLayer(
                loss_layer).has_same_projection_as(zonal_layer)
            if not have_same_projection:
                self.iface.messageBar().pushMessage(
                    tr("Error"),
                    check_projection_msg,
                    level=QgsMessageBar.CRITICAL)
                return

            # check if loss layer is raster or vector (aggregating by zone
            # is different in the two cases)
            loss_layer_is_vector = dlg.loss_layer_is_vector

            # Open dialog to ask the user to specify attributes
            # * loss from loss_layer
            # * zone_id from loss_layer
            # * svi from zonal_layer
            # * zone_id from zonal_layer
            ret_val = self.attribute_selection(
                loss_layer, zonal_layer)
            if not ret_val:
                return
            (loss_attr_names,
             zone_id_in_losses_attr_name,
             zone_id_in_zones_attr_name) = ret_val
            # aggregate losses by zone (calculate count of points in the
            # zone, sum and average loss values for the same zone)
            res = calculate_zonal_stats(loss_layer,
                                        zonal_layer,
                                        loss_attr_names,
                                        loss_layer_is_vector,
                                        zone_id_in_losses_attr_name,
                                        zone_id_in_zones_attr_name,
                                        self.iface)
            (loss_layer, zonal_layer, loss_attrs_dict) = res

            if dlg.ui.purge_chk.isChecked():
                zonal_layer = purge_zones_without_loss_points(
                    zonal_layer, loss_attrs_dict, self.iface)
            self.update_actions_status()

    def import_sv_variables(self):
        """
        Open a modal dialog to select socioeconomic variables to
        download from the openquake platform
        """

        # login to platform, to be able to retrieve sv indices
        sv_downloader = get_loggedin_downloader(self.iface)
        if sv_downloader is None:
            self.show_settings()
            return

        try:
            dlg = SelectSvVariablesDialog(sv_downloader)
            if dlg.exec_():
                dest_filename = QFileDialog.getSaveFileName(
                    dlg,
                    'Download destination',
                    os.path.expanduser("~"),
                    'Shapefiles (*.shp)')
                if dest_filename:
                    if dest_filename[-4:] != ".shp":
                        dest_filename += ".shp"
                else:
                    return
                # TODO: We should fix the workflow in case no geometries are
                # downloaded. Currently we must download them, so the checkbox
                # to let the user choose has been temporarily removed.
                # load_geometries = dlg.ui.load_geometries_chk.isChecked()
                load_geometries = True
                msg = ("Loading socioeconomic data from the OpenQuake "
                       "Platform...")
                # Retrieve the indices selected by the user
                indices_list = []
                iso_codes_list = []
                project_definition = deepcopy(PROJECT_TEMPLATE)
                svi_themes = project_definition[
                    'children'][1]['children']
                known_themes = []
                with WaitCursorManager(msg, self.iface):
                    while dlg.ui.list_multiselect.selected_widget.count() > 0:
                        item = \
                            dlg.ui.list_multiselect.selected_widget.takeItem(0)
                        ind_code = item.text().split(':')[0]
                        ind_info = dlg.indicators_info_dict[ind_code]
                        sv_theme = ind_info['theme']
                        sv_field = ind_code
                        sv_name = ind_info['name']

                        self._add_new_theme(svi_themes,
                                            known_themes,
                                            sv_theme,
                                            sv_name,
                                            sv_field)

                        indices_list.append(sv_field)
                    while dlg.ui.country_select.selected_widget.count() > 0:
                        item = \
                            dlg.ui.country_select.selected_widget.takeItem(0)
                        # get the iso from something like:
                        # country_name (iso_code)
                        iso_code = item.text().split('(')[1].split(')')[0]
                        iso_codes_list.append(iso_code)

                    # create string for DB query
                    indices_string = ",".join(indices_list)
                    iso_codes_string = ",".join(iso_codes_list)

                    assign_default_weights(svi_themes)

                    worker = DownloadPlatformDataWorker(
                        sv_downloader,
                        indices_string,
                        load_geometries,
                        iso_codes_string)
                    worker.successfully_finished.connect(
                        lambda result: self.data_download_successful(
                            result,
                            load_geometries,
                            dest_filename,
                            project_definition))
                    start_worker(worker, self.iface.messageBar(),
                                 'Downloading data from platform')
        except SvNetworkError as e:
            self.iface.messageBar().pushMessage(tr("Download Error"),
                                                tr(str(e)),
                                                level=QgsMessageBar.CRITICAL)

    def data_download_successful(
            self, result, load_geometries, dest_filename, project_definition):
        fname, msg = result
        display_msg = tr("Socioeconomic data loaded in a new layer")
        self.iface.messageBar().pushMessage(tr("Info"),
                                            tr(display_msg),
                                            level=QgsMessageBar.INFO,
                                            duration=8)
        QgsMessageLog.logMessage(msg, 'GEM Social Vulnerability Downloader')
        # don't remove the file, otherwise there will be concurrency
        # problems

        # fix an issue of QGIS 10, that is unable to read
        # multipolygons if they contain spaces between two polygons.
        # We remove those spaces from the csv file before importing it.
        # TODO: Remove this as soon as QGIS solves that issue
        for line in fileinput.input(fname, inplace=True):
            line = re.sub('\)\),\s\(\(', ')),((', line.rstrip())
            line = re.sub('\),\s\(', '),(', line.rstrip())
            # thanks to inplace=True, 'print line' writes the line into the
            # input file, overwriting the original line
            print line

        # count top lines in the csv starting with '#'
        lines_to_skip_count = count_heading_commented_lines(fname)

        url = QUrl.fromLocalFile(fname)
        url.addQueryItem('delimiter', ',')
        url.addQueryItem('skipLines', str(lines_to_skip_count))
        url.addQueryItem('trimFields', 'yes')
        if load_geometries:
            url.addQueryItem('crs', 'epsg:4326')
            url.addQueryItem('wktField', 'geometry')
        layer_uri = str(url.toEncoded())
        # create vector layer from the csv file exported by the
        # platform (it is still not editable!)
        vlayer_csv = QgsVectorLayer(layer_uri,
                                    'socioeconomic_data_export',
                                    'delimitedtext')
        if not load_geometries:
            if vlayer_csv.isValid():
                QgsMapLayerRegistry.instance().addMapLayer(vlayer_csv)
            else:
                raise RuntimeError('Layer invalid')
            layer = vlayer_csv
        else:
            result = QgsVectorFileWriter.writeAsVectorFormat(
                vlayer_csv, dest_filename, 'CP1250',
                None, 'ESRI Shapefile')
            if result != QgsVectorFileWriter.NoError:
                raise RuntimeError('Could not save shapefile')
            layer = QgsVectorLayer(
                dest_filename, 'Socioeconomic data', 'ogr')
            if layer.isValid():
                QgsMapLayerRegistry.instance().addMapLayer(layer)
            else:
                raise RuntimeError('Layer invalid')
        self.iface.setActiveLayer(layer)
        suppl_info = {
            'selected_project_definition_idx': 0,
            'project_definitions': [project_definition]}
        self.update_layer_suppl_info(layer.id(), suppl_info)
        self.update_actions_status()

    def download_layer(self):
        sv_downloader = get_loggedin_downloader(self.iface)
        if sv_downloader is None:
            self.show_settings()
            return

        dlg = DownloadLayerDialog(sv_downloader)
        if dlg.exec_():
            dest_dir = ask_for_download_destination(dlg)
            if not dest_dir:
                return

            worker = DownloadPlatformProjectWorker(sv_downloader, dlg.layer_id)
            worker.successfully_finished.connect(
                lambda zip_file: self.import_layer(
                    zip_file, sv_downloader, dest_dir, dlg))
            start_worker(worker, self.iface.messageBar(),
                         'Downloading data from platform')

    def import_layer(self, zip_file, sv_downloader, dest_dir, parent_dlg):
        files_in_zip = zip_file.namelist()
        shp_file = next(
            filename for filename in files_in_zip if '.shp' in filename)
        file_in_destination = files_exist_in_destination(
            dest_dir, files_in_zip)

        if file_in_destination:
            while confirm_overwrite(parent_dlg, file_in_destination) == \
                    QMessageBox.No:
                dest_dir = ask_for_download_destination(parent_dlg)
                if not dest_dir:
                    return
                file_in_destination = files_exist_in_destination(
                    dest_dir, zip_file.namelist())
                if not file_in_destination:
                    break

        zip_file.extractall(dest_dir)

        request_url = '%s/svir/get_supplemental_information?layer_name=%s' % (
            sv_downloader.host, parent_dlg.layer_id)
        get_supplemental_information_resp = sv_downloader.sess.get(request_url)
        if not get_supplemental_information_resp.ok:
            self.iface.messageBar().pushMessage(
                tr("Download Error"),
                tr('Unable to retrieve the project definitions for the layer'),
                level=QgsMessageBar.CRITICAL)
            return
        supplemental_information = json.loads(
            get_supplemental_information_resp.content)

        dest_file = os.path.join(dest_dir, shp_file)
        layer = QgsVectorLayer(
            dest_file,
            parent_dlg.extra_infos[parent_dlg.layer_id]['Title'], 'ogr')
        if layer.isValid():
            QgsMapLayerRegistry.instance().addMapLayer(layer)
            self.iface.messageBar().pushMessage(
                tr('Import successful'),
                tr('Shapefile imported to %s' % dest_file),
                duration=8)
        else:
            self.iface.messageBar().pushMessage(
                tr("Import Error"),
                tr('Layer invalid'),
                level=QgsMessageBar.CRITICAL)
            return
        try:
            # dlg.layer_id has the format "oqplatform:layername"
            style_name = parent_dlg.layer_id.split(':')[1] + '.sld'
            request_url = '%s/gs/rest/styles/%s' % (
                sv_downloader.host, style_name)
            get_style_resp = sv_downloader.sess.get(request_url)
            if not get_style_resp.ok:
                raise SvNetworkError(get_style_resp.reason)
            fd, sld_file = tempfile.mkstemp(suffix=".sld")
            os.close(fd)
            with open(sld_file, 'w') as f:
                f.write(get_style_resp.text)
            layer.loadSldStyle(sld_file)
        except Exception as e:
            error_msg = ('Unable to download and apply the'
                         ' style layer descriptor: %s' % e)
            self.iface.messageBar().pushMessage(
                'Error downloading style',
                error_msg, level=QgsMessageBar.WARNING,
                duration=8)
        self.iface.setActiveLayer(layer)
        try:
            project_definitions = supplemental_information[
                'project_definitions']
        except KeyError:
            project_definitions = supplemental_information
        # ensure backwards compatibility with projects with a single
        # project definition
        if not isinstance(project_definitions, list):
            project_definitions = [project_definitions]
        supplemental_information['project_definitions'] = project_definitions
        supplemental_information['platform_layer_id'] = parent_dlg.layer_id
        if 'selected_project_definition_idx' not in supplemental_information:
            supplemental_information['selected_project_definition_idx'] = 0
        self.update_layer_suppl_info(layer.id(), supplemental_information)
        self.update_actions_status()
        # in case of multiple project definitions, let the user select one
        if len(project_definitions) > 1:
            self.project_definitions_manager()

    @staticmethod
    def _add_new_theme(svi_themes,
                       known_themes,
                       indicator_theme,
                       indicator_name,
                       indicator_field):
        """add a new theme to the project_definition"""

        theme = deepcopy(THEME_TEMPLATE)
        theme['name'] = indicator_theme
        if theme['name'] not in known_themes:
            known_themes.append(theme['name'])
            svi_themes.append(theme)
        theme_position = known_themes.index(theme['name'])
        level = float('4.%d' % theme_position)
        # add a new indicator to a theme
        new_indicator = deepcopy(INDICATOR_TEMPLATE)
        new_indicator['name'] = indicator_name
        new_indicator['field'] = indicator_field
        new_indicator['level'] = level
        svi_themes[theme_position]['children'].append(new_indicator)

    def project_definitions_manager(self):
        self.sync_layer_suppl_info_from_qgs_project(
            self.iface.activeLayer().id())
        select_proj_def_dlg = ProjectsManagerDialog(self.iface)
        if select_proj_def_dlg.exec_():
            selected_project_definition = select_proj_def_dlg.selected_proj_def
            added_attrs_ids, discarded_feats, project_definition = \
                self.recalculate_indexes(selected_project_definition)
            self.notify_added_attrs_and_discarded_feats(added_attrs_ids,
                                                        discarded_feats)
            select_proj_def_dlg.suppl_info['project_definitions'][
                select_proj_def_dlg.suppl_info[
                    'selected_project_definition_idx']] = project_definition
            self.update_layer_suppl_info(self.iface.activeLayer().id(),
                                         select_proj_def_dlg.suppl_info)
            self.redraw_ir_layer(project_definition)

    def notify_added_attrs_and_discarded_feats(self,
                                               added_attrs_ids,
                                               discarded_feats):
        if added_attrs_ids:
            dp = self.iface.activeLayer().dataProvider()
            all_field_names = [field.name() for field in dp.fields()]
            added_attrs_names = [all_field_names[attr_id]
                                 for attr_id in added_attrs_ids]
            msg = ('New attributes have been added to the layer: %s'
                   % ', '.join(added_attrs_names))
            self.iface.messageBar().pushMessage(
                tr('Info'), tr(msg), level=QgsMessageBar.INFO)
        if discarded_feats:
            discarded_feats_ids_missing = [
                feat.feature_id for feat in discarded_feats
                if feat.reason == 'Missing value']
            if discarded_feats_ids_missing:
                widget = toggle_select_features_widget(
                    tr('Warning'),
                    tr('Missing values were found in some features while '
                       'calculating composite variables'),
                    tr('Select features with incomplete data'),
                    self.iface.activeLayer(),
                    discarded_feats_ids_missing,
                    self.iface.activeLayer().selectedFeaturesIds())
                self.iface.messageBar().pushWidget(widget,
                                                   QgsMessageBar.WARNING)
            discarded_feats_ids_invalid = [
                feat.feature_id for feat in discarded_feats
                if feat.reason == 'Invalid value']
            if discarded_feats_ids_invalid:
                widget = toggle_select_features_widget(
                    tr('Warning'),
                    tr('Invalid values were found in some features while '
                       'calculating composite variables using the chosen '
                       'operators (e.g. the geometric mean fails when '
                       'attempting to perform the root of a '
                       'negative value)'),
                    tr('Select features with invalid data'),
                    self.iface.activeLayer(),
                    discarded_feats_ids_invalid,
                    self.iface.activeLayer().selectedFeaturesIds())
                self.iface.messageBar().pushWidget(widget,
                                                   QgsMessageBar.WARNING)

    def weight_data(self):
        """
        Open a modal dialog to select weights in a d3.js visualization
        """
        active_layer_id = self.iface.activeLayer().id()
        # get the project definition to work with, or create a default one
        try:
            suppl_info = self.supplemental_information[active_layer_id]
            orig_project_definition = suppl_info['project_definitions'][
                suppl_info['selected_project_definition_idx']]
        except KeyError:
            orig_project_definition = deepcopy(PROJECT_TEMPLATE)
            suppl_info = {'selected_project_definition_idx': 0,
                          'project_definitions': [orig_project_definition]
                          }
            self.update_layer_suppl_info(active_layer_id, suppl_info)
        edited_project_definition = deepcopy(orig_project_definition)

        # Save the style so the following styling can be undone
        fd, sld_file_name = tempfile.mkstemp(suffix=".sld")
        os.close(fd)
        (resp_text, sld_was_saved) = \
            self.iface.activeLayer().saveSldStyle(sld_file_name)
        if sld_was_saved:
            if DEBUG:
                print 'original sld saved in %s' % sld_file_name
        else:
            err_msg = 'Unable to save the sld: %s' % resp_text
            self.iface.messageBar().pushMessage(
                tr("Warning"),
                tr(err_msg),
                level=QgsMessageBar.WARNING)

        dlg = WeightDataDialog(self.iface, edited_project_definition)
        dlg.show()
        self.redraw_ir_layer(edited_project_definition)

        dlg.json_cleaned.connect(lambda data: self.weights_changed(data, dlg))
        if dlg.exec_():
            # If the user just opens the dialog and presses OK, it probably
            # means they want to just run the index calculation, so we
            # recalculate the indexes. In case they have already made any
            # change and consequent calculations, we don't need to redo the
            # same calculation after OK is pressed.
            if not dlg.any_changes_made:
                (added_attrs_ids,
                 discarded_feats,
                 edited_project_definition) = self.recalculate_indexes(
                    dlg.project_definition)
                dlg.added_attrs_ids.update(added_attrs_ids)
                dlg.discarded_feats = discarded_feats
            else:
                edited_project_definition = deepcopy(dlg.project_definition)
            self.notify_added_attrs_and_discarded_feats(
                dlg.added_attrs_ids, dlg.discarded_feats)
            self.update_actions_status()
        else:  # 'cancel' was pressed or the dialog was closed
            if sld_was_saved:  # was able to save the original style
                self.iface.activeLayer().loadSldStyle(sld_file_name)
            # if any of the indices were saved before starting to edit the
            # tree, the corresponding fields might have been modified.
            # Therefore we recalculate the indices using the old project
            # definition
            if dlg.any_changes_made:
                edited_project_definition = deepcopy(orig_project_definition)
                iri_node = edited_project_definition
                ri_node = edited_project_definition['children'][0]
                svi_node = edited_project_definition['children'][1]
                if ('field' in iri_node
                        or 'field' in ri_node or 'field' in svi_node):
                    added_attrs_ids, _, edited_project_definition = \
                        self.recalculate_indexes(iri_node)
                    dlg.added_attrs_ids.update(added_attrs_ids)
                # delete attributes added while the dialog was open
                ProcessLayer(self.iface.activeLayer()).delete_attributes(
                    dlg.added_attrs_ids)
        dlg.json_cleaned.disconnect()
        # store the correct project definitions
        selected_idx = suppl_info['selected_project_definition_idx']
        suppl_info['project_definitions'][selected_idx] = deepcopy(
            edited_project_definition)
        self.update_layer_suppl_info(active_layer_id, suppl_info)
        self.redraw_ir_layer(edited_project_definition)

    def weights_changed(self, data, dlg):
        added_attrs_ids, discarded_feats, project_definition = \
            self.recalculate_indexes(data)
        dlg.added_attrs_ids.update(added_attrs_ids)
        dlg.discarded_feats = discarded_feats
        dlg.update_project_definition(project_definition)
        self.redraw_ir_layer(project_definition)

    def recalculate_indexes(self, data):
        project_definition = deepcopy(data)

        if self.is_iri_computable(project_definition):
            iri_node = deepcopy(project_definition)
            (added_attrs_ids, discarded_feats,
             iri_node, was_iri_computed) = calculate_composite_variable(
                self.iface, self.iface.activeLayer(), iri_node)
            project_definition = deepcopy(iri_node)
            return added_attrs_ids, discarded_feats, project_definition

        svi_added_attrs_ids = set()
        svi_discarded_feats = set()
        ri_added_attrs_ids = set()
        ri_discarded_feats = set()

        was_svi_computed = False
        if self.is_svi_computable(project_definition):
            svi_node = deepcopy(project_definition['children'][1])
            (svi_added_attrs_ids, svi_discarded_feats,
             svi_node, was_svi_computed) = calculate_composite_variable(
                self.iface, self.iface.activeLayer(), svi_node)
            project_definition['children'][1] = deepcopy(svi_node)

        was_ri_computed = False
        if self.is_ri_computable(project_definition):
            ri_node = deepcopy(project_definition['children'][0])
            (ri_added_attrs_ids, ri_discarded_feats,
             ri_node, was_ri_computed) = calculate_composite_variable(
                self.iface, self.iface.activeLayer(), ri_node)
            project_definition['children'][0] = deepcopy(ri_node)

        if not was_svi_computed and not was_ri_computed:
            return set(), set(), data
        added_attrs_ids = set()
        discarded_feats = set()
        if svi_added_attrs_ids:
            added_attrs_ids.update(svi_added_attrs_ids)
        if svi_discarded_feats:
            discarded_feats.update(svi_discarded_feats)
        if ri_added_attrs_ids:
            added_attrs_ids.update(ri_added_attrs_ids)
        if ri_discarded_feats:
            discarded_feats.update(ri_discarded_feats)
        return added_attrs_ids, discarded_feats, project_definition

    def is_svi_computable(self, proj_def):
        try:
            svi_node = proj_def['children'][1]
        except KeyError:
            return False
        # check that there is at least one theme
        if 'children' not in svi_node:
            return False
        if len(svi_node['children']) == 0:
            return False
        # check that each theme contains at least one indicator
        for theme_node in svi_node['children']:
            if 'children' not in theme_node:
                return False
            if len(theme_node['children']) == 0:
                return False
        return True

    def is_svi_renderable(self, proj_def):
        if not self.is_svi_computable(proj_def):
            return False
        # check that that the svi_node has a corresponding field
        try:
            svi_node = proj_def['children'][1]
        except KeyError:
            return False
        if 'field' not in svi_node:
            return False
        return True

    def is_ri_computable(self, proj_def):
        try:
            ri_node = proj_def['children'][0]
        except KeyError:
            return False
        # check that there is at least one risk indicator
        if 'children' not in ri_node:
            return False
        if len(ri_node['children']) == 0:
            return False
        return True

    def is_ri_renderable(self, proj_def):
        if not self.is_ri_computable(proj_def):
            return False
        try:
            ri_node = proj_def['children'][0]
        except KeyError:
            return False
        # check that that the ri_node has a corresponding field
        if 'field' not in ri_node:
            return False
        return True

    def is_iri_computable(self, proj_def):
        # check that all the sub-indices are well-defined
        if not self.is_ri_computable(proj_def):
            return False
        if not self.is_svi_computable(proj_def):
            return False
        return True

    def is_iri_renderable(self, proj_def):
        if not self.is_iri_computable(proj_def):
            return False
        iri_node = proj_def
        # check that that the iri_node has a corresponding field
        if 'field' not in iri_node:
            return False
        return True

    def redraw_ir_layer(self, data):
        # if the user has explicitly selected a field to use for styling, use
        # it, otherwise attempt to show the IRI, or the SVI, or the RI
        if 'style_by_field' in data:
            target_field = data['style_by_field']
            printing_str = target_field
        # if an IRI has been already calculated, show it
        elif self.is_iri_renderable(data):
            iri_node = data
            target_field = iri_node['field']
            printing_str = 'IRI'
        # else show the SVI if possible
        elif self.is_svi_renderable(data):
            svi_node = data['children'][1]
            target_field = svi_node['field']
            printing_str = 'SVI'
        # otherwise attempt to show the RI
        elif self.is_ri_renderable(data):
            ri_node = data['children'][0]
            target_field = ri_node['field']
            printing_str = 'RI'
        else:  # if none of them can be rendered, then do nothing
            return
        # proceed only if the target field is actually a field of the layer
        if self.iface.activeLayer().fieldNameIndex(target_field) == -1:
            return
        if DEBUG:
            import pprint
            pp = pprint.PrettyPrinter(indent=4)
            print 'REDRAWING %s using:' % printing_str
            pp.pprint(data)

        rule_renderer = QgsRuleBasedRendererV2(
            QgsSymbolV2.defaultSymbol(self.iface.activeLayer().geometryType()))
        root_rule = rule_renderer.rootRule()

        not_null_rule = root_rule.children()[0].clone()
        not_null_rule.setSymbol(QgsFillSymbolV2.createSimple(
            {'style': 'no',
             'style_border': 'no'}))
        not_null_rule.setFilterExpression('%s IS NOT NULL' % target_field)
        not_null_rule.setLabel('%s:' % target_field)
        root_rule.appendChild(not_null_rule)

        null_rule = root_rule.children()[0].clone()
        null_rule.setSymbol(QgsFillSymbolV2.createSimple(
            {'style': 'no',
             'color_border': '255,255,0,255',
             'width_border': '0.5'}))
        null_rule.setFilterExpression('%s IS NULL' % target_field)
        null_rule.setLabel(tr('Invalid value'))
        root_rule.appendChild(null_rule)

        color1 = QColor("#FFEBEB")
        color2 = QColor("red")
        classes_count = 10
        ramp = QgsVectorGradientColorRampV2(color1, color2)
        graduated_renderer = QgsGraduatedSymbolRendererV2.createRenderer(
            self.iface.activeLayer(),
            target_field,
            classes_count,
            QgsGraduatedSymbolRendererV2.Quantile,
            QgsSymbolV2.defaultSymbol(self.iface.activeLayer().geometryType()),
            ramp)

        if graduated_renderer.ranges():
            first_range_index = 0
            last_range_index = len(graduated_renderer.ranges()) - 1
            # NOTE: Workaround to avoid rounding problem (QGIS renderer's bug)
            # which creates problems styling the zone containing the lowest
            # and highest values in some cases
            lower_value = \
                graduated_renderer.ranges()[first_range_index].lowerValue()
            decreased_lower_value = floor(lower_value * 10000.0) / 10000.0
            graduated_renderer.updateRangeLowerValue(
                first_range_index, decreased_lower_value)
            upper_value = \
                graduated_renderer.ranges()[last_range_index].upperValue()
            increased_upper_value = ceil(upper_value * 10000.0) / 10000.0
            graduated_renderer.updateRangeUpperValue(
                last_range_index, increased_upper_value)
        elif DEBUG:
            print 'All features are NULL'

        # create value ranges
        rule_renderer.refineRuleRanges(not_null_rule, graduated_renderer)
        for rule in not_null_rule.children():
            label = rule.label().replace('"%s" >= ' % target_field, '')
            label = label.replace(' AND "%s" <= ' % target_field, ' - ')
            rule.setLabel(label)
        # remove default rule
        root_rule.removeChildAt(0)

        self.iface.activeLayer().setRendererV2(rule_renderer)
        self.iface.legendInterface().refreshLayerSymbology(
            self.iface.activeLayer())
        self.iface.mapCanvas().refresh()

        # NOTE: The following commented lines do not work, because they apply
        # to the active layer a solid fill and the null features are therefore
        # colored in blue instead of being transparent
        # The intent was to reset default symbol, otherwise if the user
        # attempts to re-style the layer, they will need to explicitly
        # set the border and fill). I am commenting this out for the moment.
        # root_rule.setSymbol(QgsFillSymbolV2.createSimple(
        #     {'style': 'solid',
        #      'style_border': 'solid'}))
        # self.iface.activeLayer().setRendererV2(rule_renderer)

    def show_settings(self):
        SettingsDialog(self.iface).exec_()

    def attribute_selection(self, loss_layer, zonal_layer):
        """
        Open a modal dialog containing combo boxes, allowing the user
        to select what are the attribute names for
        * loss values (from loss layer)
        * zone id (from loss layer)
        * zone id (from zonal layer)
        """
        dlg = AttributeSelectionDialog(loss_layer, zonal_layer)
        # if the user presses OK
        if dlg.exec_():
            # retrieve attribute names from selections
            loss_attr_names = \
                list(dlg.ui.loss_attrs_multisel.get_selected_items())
            # index 0 is for "use zonal geometries" (no zone id available)
            if dlg.ui.zone_id_attr_name_loss_cbox.currentIndex() == 0:
                zone_id_in_losses_attr_name = None
            else:
                zone_id_in_losses_attr_name = \
                    dlg.ui.zone_id_attr_name_loss_cbox.currentText()
            # index 0 is for "Add field with unique zone id"
            if dlg.ui.zone_id_attr_name_zone_cbox.currentIndex() == 0:
                zone_id_in_zones_attr_name = None
            else:
                zone_id_in_zones_attr_name = \
                    dlg.ui.zone_id_attr_name_zone_cbox.currentText()
            return (loss_attr_names,
                    zone_id_in_losses_attr_name,
                    zone_id_in_zones_attr_name)
        else:
            return False

    def transform_attributes(self):
        """
        A modal dialog is displayed to the user, enabling to transform one or
        more attributes of the active layer, using one of the available
        algorithms and variants
        """
        dlg = TransformationDialog(self.iface)
        reg = QgsMapLayerRegistry.instance()
        if not reg.count():
            msg = 'No layer available for transformation'
            self.iface.messageBar().pushMessage(
                tr("Error"),
                tr(msg),
                level=QgsMessageBar.CRITICAL)
            return
        if dlg.exec_():
            layer = self.iface.activeLayer()
            input_attr_names = dlg.ui.fields_multiselect.get_selected_items()
            algorithm_name = dlg.ui.algorithm_cbx.currentText()
            variant = dlg.ui.variant_cbx.currentText()
            inverse = dlg.ui.inverse_ckb.isChecked()
            for input_attr_name in input_attr_names:
                if dlg.ui.overwrite_ckb.isChecked():
                    target_attr_name = input_attr_name
                elif dlg.ui.fields_multiselect.selected_widget.count() == 1:
                    target_attr_name = dlg.ui.new_field_name_txt.text()
                else:
                    target_attr_name = ('T_' + input_attr_name)[:10]
                try:
                    with WaitCursorManager("Applying transformation",
                                           self.iface):
                        res_attr_name, invalid_input_values = ProcessLayer(
                            layer).transform_attribute(input_attr_name,
                                                       algorithm_name,
                                                       variant,
                                                       inverse,
                                                       target_attr_name)
                    msg = ('Transformation %s has been applied to attribute %s'
                           ' of layer %s.') % (algorithm_name,
                                               input_attr_name,
                                               layer.name())
                    if target_attr_name == input_attr_name:
                        msg += (' The original values of the attribute have'
                                ' been overwritten by the transformed values.')
                    else:
                        msg += (' The results of the transformation'
                                ' have been saved into the new'
                                ' attribute %s.') % (res_attr_name)
                    if invalid_input_values:
                        msg += (' The transformation could not'
                                ' be performed for the following'
                                ' input values: %s' % invalid_input_values)
                    self.iface.messageBar().pushMessage(
                        tr("Info"),
                        tr(msg),
                        level=(QgsMessageBar.INFO if not invalid_input_values
                               else QgsMessageBar.WARNING))
                except (ValueError, NotImplementedError) as e:
                    self.iface.messageBar().pushMessage(
                        tr("Error"),
                        tr(e.message),
                        level=QgsMessageBar.CRITICAL)
                self.sync_layer_suppl_info_from_qgs_project(
                    self.iface.activeLayer().id())
                active_layer_id = self.iface.activeLayer().id()
                project_definitions = self.supplemental_information[
                    'project_definitions']
                if (dlg.ui.track_new_field_ckb.isChecked()
                        and target_attr_name != input_attr_name
                        and active_layer_id in project_definitions):
                    suppl_info = self.supplemental_information[active_layer_id]
                    proj_defs = suppl_info['project_definitions']
                    for proj_def in proj_defs:
                        replace_fields(proj_def,
                                       input_attr_name,
                                       target_attr_name)
                    suppl_info['project_definitions'] = proj_defs
                    self.update_layer_suppl_info(active_layer_id, suppl_info)
        elif dlg.use_advanced:
            layer = self.iface.activeLayer()
            if layer.isModified():
                layer.commitChanges()
                layer.triggerRepaint()
                msg = 'Calculation performed on layer %s' % layer.name()
                self.iface.messageBar().pushMessage(
                    tr("Info"),
                    tr(msg),
                    level=QgsMessageBar.INFO,
                    duration=8)
        self.update_actions_status()

    def upload(self):
        temp_dir = tempfile.gettempdir()
        file_stem = '%s%sqgis_svir_%s' % (temp_dir, os.path.sep, uuid.uuid4())
        xml_file = file_stem + '.xml'

        active_layer_id = self.iface.activeLayer().id()
        self.sync_layer_suppl_info_from_qgs_project(active_layer_id)
        suppl_info = self.supplemental_information[active_layer_id]
        # add layer's bounding box
        extent = self.iface.activeLayer().extent()
        bbox = {'minx': extent.xMinimum(),
                'miny': extent.yMinimum(),
                'maxx': extent.xMaximum(),
                'maxy': extent.yMaximum()}
        suppl_info['bounding_box'] = bbox
        selected_idx = suppl_info['selected_project_definition_idx']
        proj_defs = suppl_info['project_definitions']
        project_definition = proj_defs[selected_idx]

        dlg = UploadSettingsDialog(self.iface, suppl_info)
        if dlg.exec_():
            suppl_info['title'] = dlg.ui.title_le.text()
            suppl_info['abstract'] = dlg.ui.description_te.toPlainText()
            zone_label_field = dlg.ui.zone_label_field_cbx.currentText()
            suppl_info['zone_label_field'] = zone_label_field

            license_name = dlg.ui.license_cbx.currentText()
            license_idx = dlg.ui.license_cbx.currentIndex()
            license_url = dlg.ui.license_cbx.itemData(license_idx)
            license_txt = '%s (%s)' % (license_name, license_url)
            suppl_info['license'] = license_txt
            suppl_info['svir_plugin_version'] = SVIR_PLUGIN_VERSION

            suppl_info['project_definitions'][selected_idx] = \
                project_definition
            self.update_layer_suppl_info(active_layer_id, suppl_info)

            if dlg.do_update:
                with WaitCursorManager(
                        'Updating project on the OpenQuake Platform',
                        self.iface):
                    hostname, username, password = get_credentials(self.iface)
                    session = Session()
                    try:
                        platform_login(hostname, username, password, session)
                    except SvNetworkError as e:
                        error_msg = (
                            'Unable to login to the platform: ' + e.message)
                        self.iface.messageBar().pushMessage(
                            'Error', error_msg, level=QgsMessageBar.CRITICAL)
                        return
                    if not 'platform_layer_id' in suppl_info:
                        error_msg = ('Unable to retrieve the id of'
                                     'the layer on the Platform')
                        self.iface.messageBar().pushMessage(
                            'Error', error_msg, level=QgsMessageBar.CRITICAL)
                        return
                    response = update_platform_project(
                        hostname, session, project_definition,
                        suppl_info['platform_layer_id'])
                    if response.ok:
                        self.iface.messageBar().pushMessage(
                            tr("Info"),
                            tr(response.text),
                            level=QgsMessageBar.INFO)
                    else:
                        self.iface.messageBar().pushMessage(
                            tr("Error"),
                            tr(response.text),
                            level=QgsMessageBar.CRITICAL)
            else:
                if DEBUG:
                    print 'xml_file:', xml_file
                write_iso_metadata_file(xml_file,
                                        suppl_info)
                metadata_dialog = UploadDialog(
                    self.iface, file_stem)
                metadata_dialog.upload_successful.connect(
                    self.insert_platform_layer_id)
                if metadata_dialog.exec_():
                    QDesktopServices.openUrl(QUrl(metadata_dialog.layer_url))
                elif DEBUG:
                    print "metadata_dialog cancelled"

    def insert_platform_layer_id(self, layer_url):
        platform_layer_id = layer_url.split('/')[-1]
        active_layer_id = self.iface.activeLayer().id()
        suppl_info = self.supplemental_information[active_layer_id]
        if 'platform_layer_id' not in suppl_info:
            suppl_info['platform_layer_id'] = platform_layer_id
        self.update_layer_suppl_info(active_layer_id, suppl_info)
