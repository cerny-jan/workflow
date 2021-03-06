import os
from glob import glob

from azkaban import Job
from azkaban import Project
from azkaban.util import AzkabanError

from workflow import logger
from workflow.common import yml_read, DIRTY_POSTFIX


def upload_project(session, project_name, zipfile, version, description):
    existing = {project['projectName'] for project in session.get_projects()['projects']}
    if project_name not in existing:
        logger.info("Project %s doesn't exist. Creating.", project_name)
        session.create_project(project_name, description=description)

    if version.endswith(DIRTY_POSTFIX):
        logger.warning('Uploading uncommitted version of workflow.')

    session.upload_project(project_name, zipfile)


def schedule_flow(session, project_name, flow, schedule):
    try:
        current = session.get_schedule(project_name, flow)
    except AzkabanError:
        current = None
    if current is None:
        logger.info('Scheduling %s@%s to %s', flow, project_name, schedule)
        session.schedule_cron_workflow(project_name, flow, schedule)
    elif current['cronExpression'] != schedule:
        logger.info('Rescheduling %s @ %s from %s to %s.', flow, project_name, current['cronExpression'], schedule)
        session.unschedule_workflow(project_name, flow)
        session.schedule_cron_workflow(project_name, flow, schedule)


def build_project(project_name, global_props, project_props, jobs, files, version):
    logger.info("Building workflow %s, version: %s.", project_name, version)

    project = Project(project_name, root=os.curdir, version=version)
    project.properties = global_props
    project.properties.update(project_props)

    for job_name, job_definition in jobs.items():
        project.add_job(job_name, Job(job_definition))

    for file, target in files:
        project.add_file(file, target)
    return project


def process_project(session, global_props, version, project_dir=None, project_file=None):
    if project_dir:
        project_file = os.path.join(project_dir, 'project.yml')
        project_name_candidate = os.path.basename(project_dir.rstrip('/').split(os.path.sep)[-1])
        files = [(file, file.replace(project_dir, './')) for file in
                 glob(os.path.join(project_dir, '**/*'), recursive=True)]
    else:
        project_name_candidate = os.path.basename(project_file).rstrip('.yml')
        files = []

    definition = yml_read(project_file)
    project_name = definition.get('project_name')
    if project_name is None:
        project_name = project_name_candidate

    project_props = definition.get('properties', dict())
    jobs = definition.get('jobs', dict())
    description = definition.get('description', project_name)
    schedules = definition.get('schedule', dict())
    for file, targets in definition.get('files', dict()).items():
        if type(targets == 'str'):
            targets = [targets]
        for target in targets:
            files.append((file, target))

    project = build_project(project_name, global_props, project_props, jobs, files, version)

    zipfile = '%s.zip' % project.versioned_name
    project.build(zipfile, overwrite=True)

    if session is not None:
        upload_project(session, project_name, zipfile, version, description)
        for flow, schedule in schedules.items():
            schedule_flow(session, project_name, flow, schedule)
        os.remove(zipfile)
