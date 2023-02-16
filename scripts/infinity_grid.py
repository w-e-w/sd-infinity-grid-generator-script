##################
# Stable Diffusion Infinity Grid Generator
#
# Author: Alex 'mcmonkey' Goodwin
# GitHub URL: https://github.com/mcmonkeyprojects/sd-infinity-grid-generator-script
# Created: 2022/12/08
# Last updated: 2023/02/16
# License: MIT
#
# For usage help, view the README.md file in the extension root, or via the GitHub page.
#
##################

import gradio as gr
import os
from copy import copy
from modules import images, shared, sd_models, sd_vae, sd_samplers, scripts, processing
from modules.processing import process_images, Processed
from modules.shared import opts
import gridgencore as core
from gridgencore import cleanName, getBestInList, chooseBetterFileName, GridSettingMode, fixNum, applyField, registerMode

######################### Constants #########################
refresh_symbol = '\U0001f504'  # 🔄
INF_GRID_README = "https://github.com/mcmonkeyprojects/sd-infinity-grid-generator-script"
core.EXTRA_FOOTER = 'Images area auto-generated by an AI (Stable Diffusion) and so may not have been reviewed by the page author before publishing.\n<script src="a1111webui.js?vary=9"></script>'
core.EXTRA_ASSETS = ["a1111webui.js"]

######################### Value Modes #########################

def getModelFor(name):
    return getBestInList(name, map(lambda m: m.title, sd_models.checkpoints_list.values()))

def applyModel(p, v):
    opts.sd_model_checkpoint = getModelFor(v)
    sd_models.reload_model_weights()

def cleanModel(p, v):
    actualModel = getModelFor(v)
    if actualModel is None:
        raise RuntimeError(f"Invalid parameter '{p}' as '{v}': model name unrecognized - valid {list(map(lambda m: m.title, sd_models.checkpoints_list.values()))}")
    return chooseBetterFileName(v, actualModel)

def getVaeFor(name):
    return getBestInList(name, sd_vae.vae_dict.keys())

def applyVae(p, v):
    vaeName = cleanName(v)
    if vaeName == "none":
        vaeName = "None"
    elif vaeName in ["auto", "automatic"]:
        vaeName = "Automatic"
    else:
        vaeName = getVaeFor(vaeName)
    opts.sd_vae = vaeName
    sd_vae.reload_vae_weights(None)

def cleanVae(p, v):
    vaeName = cleanName(v)
    if vaeName in ["none", "auto", "automatic"]:
        return vaeName
    actualVae = getVaeFor(vaeName)
    if actualVae is None:
        raise RuntimeError(f"Invalid parameter '{p}' as '{v}': VAE name unrecognized - valid: {list(sd_vae.vae_dict.keys())}")
    return chooseBetterFileName(v, actualVae)

def applyClipSkip(p, v):
    opts.CLIP_stop_at_last_layers = int(v)

def applyCodeformerWeight(p, v):
    opts.code_former_weight = float(v)

def applyRestoreFaces(p, v):
    input = str(v).lower().strip()
    if input == "false":
        p.restore_faces = False
        return
    p.restore_faces = True
    restorer = getBestInList(input, map(lambda m: m.name(), shared.face_restorers))
    if restorer is not None:
        opts.face_restoration_model = restorer

def applyPromptReplace(p, v):
    val = v.split('=', maxsplit=1)
    if len(val) != 2:
        raise RuntimeError(f"Invalid prompt replace, missing '=' symbol, for '{v}'")
    match = val[0].strip()
    replace = val[1].strip()
    if Script.VALIDATE_REPLACE and match not in p.prompt and match not in p.negative_prompt:
        raise RuntimeError(f"Invalid prompt replace, '{match}' is not in prompt '{p.prompt}' nor negative prompt '{p.negative_prompt}'")
    p.prompt = p.prompt.replace(match, replace)
    p.negative_prompt = p.negative_prompt.replace(match, replace)

def applyEnsd(p, v):
    opts.eta_noise_seed_delta = int(v)

def applyEnableHr(p, v):
    p.enable_hr = v
    if v:
        if p.denoising_strength is None:
            p.denoising_strength = 0.75

######################### Addons #########################
hasInited = False

def tryInit():
    global hasInited
    if hasInited:
        return
    hasInited = True
    core.gridCallInitHook = a1111GridCallInitHook
    core.gridCallParamAddHook = a1111GridCallParamAddHook
    core.gridCallApplyHook = a1111GridCallApplyHook
    core.gridRunnerPreRunHook = a1111GridRunnerPreRunHook
    core.gridRunnerPreDryHook = a1111GridRunnerPreDryHook
    core.gridRunnerRunPostDryHook = a1111GridRunnerPostDryHook
    core.webDataGetBaseParamData = a1111WebDataGetBaseParamData
    registerMode("sampler", GridSettingMode(dry=True, type="text", apply=applyField("sampler_name"), valid_list=sd_samplers.all_samplers_map.keys()))
    registerMode("seed", GridSettingMode(dry=True, type="integer", apply=applyField("seed")))
    registerMode("steps", GridSettingMode(dry=True, type="integer", min=0, max=200, apply=applyField("steps")))
    registerMode("cfg scale", GridSettingMode(dry=True, type="decimal", min=0, max=500, apply=applyField("cfg_scale")))
    registerMode("model", GridSettingMode(dry=False, type="text", apply=applyModel, clean=cleanModel))
    registerMode("vae", GridSettingMode(dry=False, type="text", apply=applyVae, clean=cleanVae))
    registerMode("width", GridSettingMode(dry=True, type="integer", apply=applyField("width")))
    registerMode("height", GridSettingMode(dry=True, type="integer", apply=applyField("height")))
    registerMode("prompt", GridSettingMode(dry=True, type="text", apply=applyField("prompt")))
    registerMode("negative prompt", GridSettingMode(dry=True, type="text", apply=applyField("negative_prompt")))
    registerMode("var seed", GridSettingMode(dry=True, type="integer", apply=applyField("subseed")))
    registerMode("var strength", GridSettingMode(dry=True, type="decimal", min=0, max=1, apply=applyField("subseed_strength")))
    registerMode("clipskip", GridSettingMode(dry=False, type="integer", min=1, max=12, apply=applyClipSkip))
    registerMode("denoising", GridSettingMode(dry=True, type="decimal", min=0, max=1, apply=applyField("denoising_strength")))
    registerMode("eta", GridSettingMode(dry=True, type="decimal", min=0, max=1, apply=applyField("eta")))
    registerMode("sigma churn", GridSettingMode(dry=True, type="decimal", min=0, max=1, apply=applyField("s_churn")))
    registerMode("sigma tmin", GridSettingMode(dry=True, type="decimal", min=0, max=1, apply=applyField("s_tmin")))
    registerMode("sigma tmax", GridSettingMode(dry=True, type="decimal", min=0, max=1, apply=applyField("s_tmax")))
    registerMode("sigma noise", GridSettingMode(dry=True, type="decimal", min=0, max=1, apply=applyField("s_noise")))
    registerMode("out width", GridSettingMode(dry=True, type="integer", min=0, apply=applyField("inf_grid_out_width")))
    registerMode("out height", GridSettingMode(dry=True, type="integer", min=0, apply=applyField("inf_grid_out_height")))
    registerMode("restore faces", GridSettingMode(dry=True, type="text", apply=applyRestoreFaces, valid_list=lambda: list(map(lambda m: m.name(), shared.face_restorers)) + ["true", "false"]))
    registerMode("codeformer weight", GridSettingMode(dry=True, type="decimal", min=0, max=1, apply=applyCodeformerWeight))
    registerMode("prompt replace", GridSettingMode(dry=True, type="text", apply=applyPromptReplace))
    registerMode("tiling", GridSettingMode(dry=True, type="boolean", apply=applyField("tiling")))
    registerMode("image mask weight", GridSettingMode(dry=True, type="decimal", min=0, max=1, apply=applyField("inpainting_mask_weight")))
    registerMode("eta noise seed delta", GridSettingMode(dry=True, type="integer", apply=applyEnsd))
    registerMode("enable highres fix", GridSettingMode(dry=True, type="boolean", apply=applyEnableHr))
    registerMode("highres scale", GridSettingMode(dry=True, type="decimal", min=1, max=16, apply=applyField("hr_scale")))
    registerMode("highres steps", GridSettingMode(dry=True, type="integer", min=0, max=200, apply=applyField("hr_second_pass_steps")))
    registerMode("highres resize width", GridSettingMode(dry=True, type="integer", apply=applyField("hr_resize_x")))
    registerMode("highres resize height", GridSettingMode(dry=True, type="integer", apply=applyField("hr_resize_y")))
    registerMode("highres upscale to width", GridSettingMode(dry=True, type="integer", apply=applyField("hr_upscale_to_x")))
    registerMode("highres upscale to height", GridSettingMode(dry=True, type="integer", apply=applyField("hr_upscale_to_y")))
    registerMode("highres upscaler", GridSettingMode(dry=True, type="text", apply=applyField("hr_upscaler"), valid_list=lambda: list(map(lambda u: u.name, shared.sd_upscalers)) + list(shared.latent_upscale_modes.keys())))
    try:
        scriptList = [x for x in scripts.scripts_data if x.script_class.__module__ == "dynamic_thresholding.py"][:1]
        if len(scriptList) == 1:
            dynamic_thresholding = scriptList[0].module
            def applyEnable(p, v):
                p.dynthres_enabled = bool(v)
            registerMode("dynamicthresholdenable", GridSettingMode(dry=True, type="boolean", apply=applyEnable))
            def applyMimicScale(p, v):
                p.dynthres_mimic_scale = float(v)
            registerMode("dynamicthresholdmimicscale", GridSettingMode(dry=True, type="decimal", min=0, max=500, apply=applyMimicScale))
            def applyThresholdPercentile(p, v):
                p.dynthres_threshold_percentile = float(v)
            registerMode("dynamicthresholdthresholdpercentile", GridSettingMode(dry=True, type="decimal", min=0.0, max=100.0, apply=applyThresholdPercentile))
            def applyMimicMode(p, v):
                mode = getBestInList(v, dynamic_thresholding.VALID_MODES)
                if mode is None:
                    raise RuntimeError(f"Invalid parameter '{p}' as '{v}': dynthres mode name unrecognized - valid: {dynamic_thresholding.VALID_MODES}")
                p.dynthres_mimic_mode = mode
            registerMode("dynamicthresholdmimicmode", GridSettingMode(dry=True, type="text", apply=applyMimicMode))
            def applyCfgMode(p, v):
                p.dynthres_cfg_mode = v
            def cleanCfgMode(p, v):
                mode = getBestInList(v, dynamic_thresholding.VALID_MODES)
                if mode is None:
                    raise RuntimeError(f"Invalid parameter '{p}' as '{v}': dynthres mode name unrecognized - valid: {dynamic_thresholding.VALID_MODES}")
                return mode
            registerMode("dynamicthresholdcfgmode", GridSettingMode(dry=True, type="text", apply=applyCfgMode, clean=cleanCfgMode))
            def applyMimicScaleMin(p, v):
                p.dynthres_mimic_scale_min = float(v)
            registerMode("dynamicthresholdmimicscaleminimum", GridSettingMode(dry=True, type="decimal", min=0.0, max=100.0, apply=applyMimicScaleMin))
            def applyCfgScaleMin(p, v):
                p.dynthres_cfg_scale_min = float(v)
            registerMode("dynamicthresholdcfgscaleminimum", GridSettingMode(dry=True, type="decimal", min=0.0, max=100.0, apply=applyCfgScaleMin))
            def applyExperimentMode(p, v):
                p.dynthres_experiment_mode = int(v)
            registerMode("dynamicthresholdexperimentmode", GridSettingMode(dry=True, type="integer", min=0, max=100, apply=applyExperimentMode))
            def applyPowerValue(p, v):
                p.dynthres_power_val = float(v)
            registerMode("dynamicthresholdpowervalue", GridSettingMode(dry=True, type="decimal", min=0, max=100, apply=applyPowerValue))
    except ModuleNotFoundError as e:
        print(f"Infinity Grid Generator failed to import a dependency module: {e}")
        pass

######################### Actual Execution Logic #########################

def a1111GridCallInitHook(gridCall):
    gridCall.replacements = list()

def a1111GridCallParamAddHook(gridCall, p, v):
    if cleanName(p) == "promptreplace":
        gridCall.replacements.append(v)
        return True
    return False

def a1111GridCallApplyHook(gridCall, p, dry):
    for replace in gridCall.replacements:
        applyPromptReplace(p, replace)
    
def a1111GridRunnerPreRunHook(gridRunner):
    shared.total_tqdm.updateTotal(gridRunner.totalSteps)

class TempHolder: pass

def a1111GridRunnerPreDryHook(gridRunner):
    gridRunner.temp = TempHolder()
    gridRunner.temp.oldClipSkip = opts.CLIP_stop_at_last_layers
    gridRunner.temp.oldCodeformerWeight = opts.code_former_weight
    gridRunner.temp.oldFaceRestorer = opts.face_restoration_model
    gridRunner.temp.eta_noise_seed_delta = opts.eta_noise_seed_delta
    gridRunner.temp.oldVae = opts.sd_vae
    gridRunner.temp.oldModel = opts.sd_model_checkpoint

def a1111GridRunnerPostDryHook(gridRunner, p, set):
    p.seed = processing.get_fixed_seed(p.seed)
    p.subseed = processing.get_fixed_seed(p.subseed)
    processed = process_images(p)
    if len(processed.images) != 1:
        raise RuntimeError(f"Something went wrong! Image gen '{set.data}' produced {len(processed.images)} images, which is wrong")
    os.makedirs(os.path.dirname(set.filepath), exist_ok=True)
    if hasattr(p, 'inf_grid_out_width') and hasattr(p, 'inf_grid_out_height'):
        processed.images[0] = processed.images[0].resize((p.inf_grid_out_width, p.inf_grid_out_height), resample=images.LANCZOS)
    info = processing.create_infotext(p, [p.prompt], [p.seed], [p.subseed], [])
    images.save_image(processed.images[0], path=os.path.dirname(set.filepath), basename="", forced_filename=os.path.basename(set.filepath), save_to_dirs=False, info=info, extension=gridRunner.grid.format, p=p, prompt=p.prompt, seed=processed.seed)
    opts.CLIP_stop_at_last_layers = gridRunner.temp.oldClipSkip
    opts.code_former_weight = gridRunner.temp.oldCodeformerWeight
    opts.face_restoration_model = gridRunner.temp.oldFaceRestorer
    opts.sd_vae = gridRunner.temp.oldVae
    opts.sd_model_checkpoint = gridRunner.temp.oldModel
    opts.eta_noise_seed_delta = gridRunner.temp.eta_noise_seed_delta
    gridRunner.temp = None
    return processed

def a1111WebDataGetBaseParamData(p):
    return {
        "sampler": p.sampler_name,
        "seed": p.seed,
        "restorefaces": (opts.face_restoration_model if p.restore_faces else None),
        "steps": p.steps,
        "cfgscale": p.cfg_scale,
        "model": chooseBetterFileName('', shared.sd_model.sd_checkpoint_info.model_name).replace(',', '').replace(':', ''),
        "vae": (None if sd_vae.loaded_vae_file is None else (chooseBetterFileName('', sd_vae.loaded_vae_file).replace(',', '').replace(':', ''))),
        "width": p.width,
        "height": p.height,
        "prompt": p.prompt,
        "negativeprompt": p.negative_prompt,
        "varseed": (None if p.subseed_strength == 0 else p.subseed),
        "varstrength": (None if p.subseed_strength == 0 else p.subseed_strength),
        "clipskip": opts.CLIP_stop_at_last_layers,
        "codeformerweight": opts.code_former_weight,
        "denoising": getattr(p, 'denoising_strength', None),
        "eta": fixNum(p.eta),
        "sigmachurn": fixNum(p.s_churn),
        "sigmatmin": fixNum(p.s_tmin),
        "sigmatmax": fixNum(p.s_tmax),
        "sigmanoise": fixNum(p.s_noise),
        "ENSD": None if opts.eta_noise_seed_delta == 0 else opts.eta_noise_seed_delta
    }

class SettingsFixer():
    def __enter__(self):
        self.model = opts.sd_model_checkpoint
        self.CLIP_stop_at_last_layers = opts.CLIP_stop_at_last_layers
        self.code_former_weight = opts.code_former_weight
        self.face_restoration_model = opts.face_restoration_model
        self.eta_noise_seed_delta = opts.eta_noise_seed_delta
        self.vae = opts.sd_vae

    def __exit__(self, exc_type, exc_value, tb):
        opts.code_former_weight = self.code_former_weight
        opts.face_restoration_model = self.face_restoration_model
        opts.CLIP_stop_at_last_layers = self.CLIP_stop_at_last_layers
        opts.eta_noise_seed_delta = self.eta_noise_seed_delta
        opts.sd_vae = self.vae
        opts.sd_model_checkpoint = self.model
        sd_models.reload_model_weights()
        sd_vae.reload_vae_weights()

######################### Script class entrypoint #########################
class Script(scripts.Script):
    BASEDIR = scripts.basedir()
    VALIDATE_REPLACE = True

    def title(self):
        return "Generate Infinite-Axis Grid"

    def show(self, is_img2img):
        return True

    def ui(self, is_img2img):
        tryInit()
        gr.HTML(value=f"<br>Confused/new? View <a style=\"border-bottom: 1px #00ffff dotted;\" href=\"{INF_GRID_README}\">the README</a> for usage instructions.<br><br>")
        do_overwrite = gr.Checkbox(value=False, label="Overwrite existing images (for updating grids)")
        generate_page = gr.Checkbox(value=True, label="Generate infinite-grid webviewer page")
        dry_run = gr.Checkbox(value=False, label="Do a dry run to validate your grid file")
        validate_replace = gr.Checkbox(value=True, label="Validate PromptReplace input")
        publish_gen_metadata = gr.Checkbox(value=True, label="Publish full generation metadata for viewing on-page")
        fast_skip = gr.Checkbox(value=False, label="Use more-performant skipping")
        # Maintain our own refreshable list of yaml files, to avoid all the oddities of other scripts demanding you drag files and whatever
        # Refresh code based roughly on how the base WebUI does refreshing of model files and all
        with gr.Row():
            grid_file = gr.Dropdown(value=None,label="Select grid definition file", choices=core.getNameList())
            def refresh():
                newChoices = core.getNameList()
                grid_file.choices = newChoices
                return gr.update(choices=newChoices)
            refresh_button = gr.Button(value=refresh_symbol, elem_id="infinity_grid_refresh_button")
            refresh_button.click(fn=refresh, inputs=[], outputs=[grid_file])
        output_file_path = gr.Textbox(value="", label="Output folder name (if blank uses yaml filename)")
        def getPageUrlText(file):
            if file is None:
                return "(...)"
            outPath = opts.outdir_grids or (opts.outdir_img2img_grids if is_img2img else opts.outdir_txt2img_grids)
            fullOutPath = os.path.join(outPath, file)
            return f"Page will be at <a style=\"border-bottom: 1px #00ffff dotted;\" href=\"/file={fullOutPath}/index.html\">(Click me) <code>{fullOutPath}</code></a><br>"
        page_will_be = gr.HTML(value="(...)")
        def updatePageUrl(filePath, selectedFile):
            return gr.update(value=getPageUrlText(filePath or (selectedFile.replace(".yml", "") if selectedFile is not None else None)))
        output_file_path.change(fn=updatePageUrl, inputs=[output_file_path, grid_file], outputs=[page_will_be])
        grid_file.change(fn=updatePageUrl, inputs=[output_file_path, grid_file], outputs=[page_will_be])
        return [do_overwrite, generate_page, dry_run, validate_replace, publish_gen_metadata, grid_file, fast_skip, output_file_path]

    def run(self, p, do_overwrite, generate_page, dry_run, validate_replace, publish_gen_metadata, grid_file, fast_skip, output_file_path):
        tryInit()
        # Clean up default params
        p = copy(p)
        p.n_iter = 1
        p.batch_size = 1
        p.do_not_save_samples = True
        p.do_not_save_grid = True
        p.seed = processing.get_fixed_seed(p.seed)
        # Store extra variable
        Script.VALIDATE_REPLACE = validate_replace
        # Validate to avoid abuse
        if '..' in grid_file or grid_file == "":
            raise RuntimeError(f"Unacceptable filename '{grid_file}'")
        if '..' in output_file_path:
            raise RuntimeError(f"Unacceptable alt file path '{output_file_path}'")
        with SettingsFixer():
            result = core.runGridGen(p, grid_file, p.outpath_grids, output_file_path, do_overwrite, fast_skip, generate_page, publish_gen_metadata, dry_run)
        if result is None:
            return Processed(p, list())
        return result
