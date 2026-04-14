from typing import Any, Dict
from dataclasses import asdict
from datetime import datetime
from ...core.jobs import JobManager, JobStatus
from ...utils.debug_log import debug_log
from ..code_finder import CodeFinder

def list_indexed_repositories(code_finder: CodeFinder, **args) -> Dict[str, Any]:
    """Tool to list indexed repositories."""
    try:
        debug_log("Listing indexed repositories.")
        results = code_finder.list_indexed_repositories()
        return {
            "success": True,
            "repositories": results
        }
    except Exception as e:
        debug_log(f"Error listing indexed repositories: {str(e)}")
        return {"error": f"Failed to list indexed repositories: {str(e)}"}

def check_job_status(job_manager: JobManager, **args) -> Dict[str, Any]:
    """Tool to check job status"""
    job_id = args.get("job_id")
    if not job_id:
        return {"error": "Job ID is a required argument."}
            
    try:
        job = job_manager.get_job(job_id)
        
        if not job:
            return {
                "success": False,
                "status": "not_found",
                "error_code": "JOB_NOT_FOUND",
                "message": f"Job with ID '{job_id}' not found. The ID may be incorrect or the job may have been cleared after a server restart."
            }
        
        job_dict = asdict(job)
        
        if job.status == JobStatus.RUNNING:
            if job.estimated_time_remaining:
                remaining = job.estimated_time_remaining
                job_dict["estimated_time_remaining_human"] = (
                    f"{int(remaining // 60)}m {int(remaining % 60)}s" 
                    if remaining >= 60 else f"{int(remaining)}s"
                )
            
            if job.start_time:
                elapsed = (datetime.now() - job.start_time).total_seconds()
                job_dict["elapsed_time_human"] = (
                    f"{int(elapsed // 60)}m {int(elapsed % 60)}s" 
                    if elapsed >= 60 else f"{int(elapsed)}s"
                )
        
        elif job.status == JobStatus.COMPLETED and job.start_time and job.end_time:
            duration = (job.end_time - job.start_time).total_seconds()
            job_dict["actual_duration_human"] = (
                f"{int(duration // 60)}m {int(duration % 60)}s" 
                if duration >= 60 else f"{int(duration)}s"
            )
        
        job_dict["start_time"] = job.start_time.strftime("%Y-%m-%d %H:%M:%S")
        if job.end_time:
            job_dict["end_time"] = job.end_time.strftime("%Y-%m-%d %H:%M:%S")
        
        job_dict["status"] = job.status.value
        
        return {"success": True, "job": job_dict}
    
    except Exception as e:
        debug_log(f"Error checking job status: {str(e)}")
        return {"error": f"Failed to check job status: {str(e)}"}

def list_jobs(job_manager: JobManager) -> Dict[str, Any]:
    """Tool to list all jobs"""
    try:
        jobs = job_manager.list_jobs()
        
        jobs_data = []
        for job in jobs:
            job_dict = asdict(job)
            job_dict["status"] = job.status.value
            job_dict["start_time"] = job.start_time.strftime("%Y-%m-%d %H:%M:%S")
            if job.end_time:
                job_dict["end_time"] = job.end_time.strftime("%Y-%m-%d %H:%M:%S")
            jobs_data.append(job_dict)
        
        jobs_data.sort(key=lambda x: x["start_time"], reverse=True)
        
        return {"success": True, "jobs": jobs_data, "total_jobs": len(jobs_data)}
    
    except Exception as e:
        debug_log(f"Error listing jobs: {str(e)}")
        return {"error": f"Failed to list jobs: {str(e)}"}


def search_registry_bundles(code_finder: CodeFinder, **args) -> Dict[str, Any]:
    """Tool to search for bundles in the registry."""
    from ...core.bundle_registry import BundleRegistry
    
    query = args.get("query", "").lower()
    unique_only = args.get("unique_only", False)
    
    try:
        debug_log(f"Searching registry for: {query}")
        
        # Fetch directly from core registry
        bundles = BundleRegistry.fetch_available_bundles()
        
        if not bundles:
            return {
                "success": True,
                "bundles": [],
                "total": 0,
                "message": "No bundles found in registry"
            }
        
        # Filter by query if provided
        if query:
            filtered_bundles = []
            for bundle in bundles:
                name = bundle.get('name', '').lower()
                repo = bundle.get('repo', '').lower()
                full_name = bundle.get('full_name', '').lower()
                
                if query in name or query in repo or query in full_name:
                    filtered_bundles.append(bundle)
            bundles = filtered_bundles
        
        # If unique_only, keep only most recent version per package
        if unique_only:
            unique_bundles = {}
            for bundle in bundles:
                base_name = bundle.get('name', 'unknown')
                if base_name not in unique_bundles:
                    unique_bundles[base_name] = bundle
                else:
                    current_time = bundle.get('generated_at', '')
                    existing_time = unique_bundles[base_name].get('generated_at', '')
                    if current_time > existing_time:
                        unique_bundles[base_name] = bundle
            bundles = list(unique_bundles.values())
        
        # Sort by name
        bundles.sort(key=lambda b: (b.get('name', ''), b.get('full_name', '')))
        
        return {
            "success": True,
            "bundles": bundles,
            "total": len(bundles),
            "query": query if query else "all",
            "unique_only": unique_only
        }
    
    except Exception as e:
        debug_log(f"Error searching registry: {str(e)}")
        return {"error": f"Failed to search registry: {str(e)}"}


def get_repository_stats(code_finder: CodeFinder, **args) -> Dict[str, Any]:
    """Tool to get statistics about indexed repositories."""
    from pathlib import Path
    
    repo_path = args.get("repo_path")
    
    try:
        debug_log(f"Getting stats for: {repo_path or 'all repositories'}")
        
        with code_finder.db_manager.get_driver().session() as session:
            if repo_path:
                # Stats for specific repository
                repo_path_obj = str(Path(repo_path).resolve())
                
                # Check if repository exists
                repo_query = """
                MATCH (r:Repository {path: $path})
                RETURN r
                """
                result = session.run(repo_query, path=repo_path_obj)
                if not result.single():
                    return {
                        "success": False,
                        "error": f"Repository not found: {repo_path_obj}"
                    }
                
                # 1. Files
                file_query = "MATCH (r:Repository {path: $path})-[:CONTAINS*]->(f:File) RETURN count(f) as c"
                file_count = session.run(file_query, path=repo_path_obj).single()["c"]
                
                # 2. Functions
                func_query = "MATCH (r:Repository {path: $path})-[:CONTAINS*]->(func:Function) RETURN count(func) as c"
                func_count = session.run(func_query, path=repo_path_obj).single()["c"]
                
                # 3. Classes
                class_query = "MATCH (r:Repository {path: $path})-[:CONTAINS*]->(cls:Class) RETURN count(cls) as c"
                class_count = session.run(class_query, path=repo_path_obj).single()["c"]
                
                # 4. Modules (imported)
                module_query = "MATCH (r:Repository {path: $path})-[:CONTAINS*]->(f:File)-[:IMPORTS]->(m:Module) RETURN count(DISTINCT m) as c"
                module_count = session.run(module_query, path=repo_path_obj).single()["c"]
                
                return {
                    "success": True,
                    "repository": repo_path_obj,
                    "stats": {
                        "files": file_count,
                        "functions": func_count,
                        "classes": class_count,
                        "modules": module_count
                    }
                }
            else:
                # Overall database stats
                repo_count = session.run("MATCH (r:Repository) RETURN count(r) as c").single()["c"]
                
                if repo_count > 0:
                    file_count = session.run("MATCH (f:File) RETURN count(f) as c").single()["c"]
                    func_count = session.run("MATCH (func:Function) RETURN count(func) as c").single()["c"]
                    class_count = session.run("MATCH (cls:Class) RETURN count(cls) as c").single()["c"]
                    module_count = session.run("MATCH (m:Module) RETURN count(m) as c").single()["c"]
                    
                    return {
                        "success": True,
                        "stats": {
                            "repositories": repo_count,
                            "files": file_count,
                            "functions": func_count,
                            "classes": class_count,
                            "modules": module_count
                        }
                    }
                else:
                    return {
                        "success": True,
                        "stats": {},
                        "message": "No data indexed yet"
                    }
    
    except Exception as e:
        debug_log(f"Error getting stats: {str(e)}")
        return {"error": f"Failed to get stats: {str(e)}"}
